#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Gather relevant Wikidata and target catalog data for matching and validation purposes."""

__author__ = 'Marco Fossati'
__email__ = 'fossati@spaziodati.eu'
__version__ = '1.0'
__license__ = 'GPL-3.0'
__copyright__ = 'Copyleft 2018, Hjfocs'

import json
import logging
import re
import sys
from collections import defaultdict
from typing import Iterable

import regex
from sqlalchemy import or_

from soweego.commons import constants, target_database, url_utils
from soweego.commons.cache import cached
from soweego.commons.db_manager import DBManager
from soweego.importer import models
from soweego.wikidata import api_requests, sparql_queries, vocabulary

LOGGER = logging.getLogger(__name__)


def gather_target_metadata(entity_type, catalog):
    catalog_constants = _get_catalog_constants(catalog)
    catalog_entity = _get_catalog_entity(entity_type, catalog_constants)

    LOGGER.info(
        'Gathering %s birth/death dates/places and gender metadata ...', catalog)
    entity = catalog_entity['entity']
    # Base metadata
    query_fields = _build_metadata_query_fields(entity, entity_type, catalog)

    session = DBManager.connect_to_db()
    query = session.query(
        *query_fields).filter(or_(entity.born.isnot(None), entity.died.isnot(None)))
    result = None
    try:
        raw_result = _run_query(query, catalog, entity_type)
        if raw_result is None:
            return None
        result = _parse_target_metadata_query_result(raw_result)
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()
    return result


def tokens_fulltext_search(target_entity: constants.DB_ENTITY, boolean_mode: bool, tokens: Iterable[str], where_clause: filter = None, limit: int = 10) -> Iterable[constants.DB_ENTITY]:
    if issubclass(target_entity, models.base_entity.BaseEntity):
        column = target_entity.name_tokens
    elif issubclass(target_entity, models.base_link_entity.BaseLinkEntity):
        column = target_entity.url_tokens
    elif issubclass(target_entity, models.base_nlp_entity.BaseNlpEntity):
        column = target_entity.description_tokens
    else:
        LOGGER.critical('Bad target entity class: %s', target_entity)
        raise ValueError('Bad target entity class: %s' % target_entity)

    terms = ' '.join(map('+{0}'.format, tokens)
                     ) if boolean_mode else ' '.join(tokens)
    ft_search = column.match(terms)

    session = DBManager.connect_to_db()
    try:
        if where_clause is None:
            query = session.query(target_entity).filter(
                ft_search).limit(limit)
        else:
            query = session.query(target_entity).filter(
                ft_search).filter(where_clause).limit(limit)

        count = query.count()
        if count == 0:
            LOGGER.debug(
                "No result from full-text index query to %s. Terms: '%s'", target_entity.__name__, terms)
            session.commit()
        else:
            for row in query:
                yield row
            session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


def name_fulltext_search(target_entity: constants.DB_ENTITY, query: str) -> Iterable[constants.DB_ENTITY]:
    ft_search = target_entity.name.match(query)

    session = DBManager.connect_to_db()
    try:
        for r in session.query(target_entity).filter(ft_search).all():
            yield r
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


def perfect_name_search(target_entity: constants.DB_ENTITY, to_search: str) -> Iterable[constants.DB_ENTITY]:
    session = DBManager.connect_to_db()
    try:
        for r in session.query(target_entity).filter(
                target_entity.name == to_search).all():
            yield r

    except:
        session.rollback()
        raise
    finally:
        session.close()


def gather_target_dataset(entity_type, catalog, identifiers, fileout, for_classification):
    base, link, nlp = target_database.get_entity(catalog, entity_type), target_database.get_link_entity(
        catalog, entity_type), target_database.get_nlp_entity(catalog, entity_type)
    if for_classification:
        condition = ~base.catalog_id.in_(identifiers)
        to_log = 'dataset'
    else:
        condition = base.catalog_id.in_(identifiers)
        to_log = 'training set'

    LOGGER.info(
        'Gathering %s %s for the linker ...', catalog, to_log)

    session = DBManager.connect_to_db()
    query = session.query(base, link, nlp).outerjoin(link, base.catalog_id == link.catalog_id).outerjoin(
        nlp, base.catalog_id == nlp.catalog_id).filter(condition)

    try:
        result = _run_query(query, catalog, entity_type)
        if result is None:
            sys.exit(1)
        relevant_fields = _build_dataset_relevant_fields(base, link, nlp)
        _dump_target_dataset_query_result(
            result, relevant_fields, fileout)
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


def _build_dataset_relevant_fields(base, link, nlp):
    fields = set()
    for entity in base, link, nlp:
        for column in entity.__mapper__.column_attrs:
            field = column.key
            if field in ('internal_id', 'catalog_id'):
                continue
            fields.add(field)
    return fields


def _dump_target_dataset_query_result(result, relevant_fields, fileout):
    for base, link, nlp in result:
        parsed = {constants.TID: base.catalog_id}
        for field in relevant_fields:
            try:
                parsed[field] = getattr(base, field)
            except AttributeError:
                pass
            try:
                parsed[field] = getattr(link, field)
            except AttributeError:
                pass
            try:
                parsed[field] = getattr(nlp, field)
            except AttributeError:
                pass

        fileout.write(json.dumps(parsed, ensure_ascii=False) + '\n')
        fileout.flush()


def _run_query(query, catalog, entity_type, page=1000):
    count = query.count()
    if count == 0:
        LOGGER.warning(
            "No data available for %s %s. Stopping here", catalog, entity_type)
        return None
    LOGGER.info('Got %d internal IDs with data from %s %s',
                count, catalog, entity_type)
    return query.yield_per(page).enable_eagerloads(False)


def _build_metadata_query_fields(entity, entity_type, catalog):
    # Base metadata
    query_fields = [entity.catalog_id, entity.born,
                    entity.born_precision, entity.died, entity.died_precision]
    # Check additional metadata
    if hasattr(entity, 'gender'):
        query_fields.append(entity.gender)
    else:
        LOGGER.info('%s %s has no gender information', catalog, entity_type)
    if hasattr(entity, 'birth_place'):
        query_fields.append(entity.birth_place)
    else:
        LOGGER.info('%s %s has no birth place information',
                    catalog, entity_type)
    if hasattr(entity, 'death_place'):
        query_fields.append(entity.death_place)
    else:
        LOGGER.info('%s %s has no death place information',
                    catalog, entity_type)
    return query_fields


def _parse_target_metadata_query_result(result_set):
    for result in result_set:
        identifier = result.catalog_id
        born = result.born
        if born:
            # Default date precision when not available: 9 (year)
            born_precision = getattr(result, 'born_precision', 9)
            date_of_birth = f'{born}/{born_precision}'
            yield identifier, vocabulary.DATE_OF_BIRTH, date_of_birth
        else:
            LOGGER.debug('%s: no birth date available', identifier)
        died = result.died
        if died:
            died_precision = getattr(result, 'died_precision', 9)
            date_of_death = f'{died}/{died_precision}'
            yield identifier, vocabulary.DATE_OF_DEATH, date_of_death
        else:
            LOGGER.debug('%s: no death date available', identifier)
        if hasattr(result, 'gender'):
            yield identifier, vocabulary.SEX_OR_GENDER, result.gender
        else:
            LOGGER.debug('%s: no gender available', identifier)
        if hasattr(result, 'birth_place'):
            yield identifier, vocabulary.PLACE_OF_BIRTH, result.birth_place
        else:
            LOGGER.debug('%s: no birth place available', identifier)
        if hasattr(result, 'death_place'):
            yield identifier, vocabulary.PLACE_OF_DEATH, result.death_place
        else:
            LOGGER.debug('%s: no death place available', identifier)


@cached
def gather_target_links(entity_type, catalog):
    catalog_constants = _get_catalog_constants(catalog)
    catalog_entity = _get_catalog_entity(entity_type, catalog_constants)

    LOGGER.info('Gathering %s %s links ...', catalog, entity_type)
    link_entity = catalog_entity['link_entity']

    session = DBManager.connect_to_db()
    result = None
    try:
        query = session.query(link_entity.catalog_id, link_entity.url)
        count = query.count()
        if count == 0:
            LOGGER.warning(
                "No links available for %s %s. Stopping validation here", catalog, entity_type)
            return None
        LOGGER.info('Got %d links from %s %s', count, catalog, entity_type)
        result = query.all()
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()

    if result is None:
        return None
    for row in result:
        yield row.catalog_id, row.url


def _get_catalog_entity(entity_type, catalog_constants):
    catalog_entity = catalog_constants.get(entity_type)
    if not catalog_entity:
        LOGGER.critical('Bad entity type: %s. It should be one of %s',
                        entity_type, catalog_constants)
        raise ValueError('Bad entity type: %s. It should be one of %s' %
                         (entity_type, catalog_constants.keys()))
    return catalog_entity


def _get_catalog_constants(catalog):
    catalog_constants = constants.TARGET_CATALOGS.get(catalog)
    if not catalog_constants:
        LOGGER.critical('Bad catalog: %s. It should be one of %s',
                        catalog, constants.TARGET_CATALOGS.keys())
        raise ValueError('Bad catalog: %s. It should be one of %s' %
                         (catalog, constants.TARGET_CATALOGS.keys()))
    return catalog_constants


def gather_wikidata_metadata(wikidata):
    LOGGER.info(
        'Gathering Wikidata birth/death dates/places and gender metadata from the Web API. This will take a while ...')
    total = 0
    # Generator of generators
    for entity in api_requests.get_metadata(wikidata.keys()):
        for qid, pid, value in entity:
            parsed = api_requests.parse_wikidata_value(value)
            if not wikidata[qid].get('metadata'):
                wikidata[qid]['metadata'] = set()
            wikidata[qid]['metadata'].add((pid, parsed))
            total += 1
    LOGGER.info('Got %d statements', total)


def gather_wikidata_links(wikidata, url_pids, ext_id_pids_to_urls):
    LOGGER.info(
        'Gathering Wikidata sitelinks, third-party links, and external identifier links from the Web API. This will take a while ...')
    total = 0
    for iterator in api_requests.get_links(wikidata.keys(), url_pids, ext_id_pids_to_urls):
        for qid, url in iterator:
            if not wikidata[qid].get('links'):
                wikidata[qid]['links'] = set()
            wikidata[qid]['links'].add(url)
            total += 1
    LOGGER.info('Got %d links', total)


def gather_relevant_pids():
    url_pids = set()
    for result in sparql_queries.url_pids_query():
        url_pids.add(result)
    ext_id_pids_to_urls = defaultdict(dict)
    for result in sparql_queries.external_id_pids_and_urls_query():
        for pid, formatters in result.items():
            for formatter_url, formatter_regex in formatters.items():
                if formatter_regex:
                    try:
                        compiled_regex = re.compile(formatter_regex)
                    except re.error:
                        LOGGER.debug(
                            "Using 'regex' third-party library. Formatter regex not supported by the 're' standard library: %s", formatter_regex)
                        try:
                            compiled_regex = regex.compile(formatter_regex)
                        except regex.error:
                            LOGGER.debug(
                                "Giving up. Formatter regex not supported by 'regex': %s", formatter_regex)
                            compiled_regex = None
                else:
                    compiled_regex = None
                ext_id_pids_to_urls[pid][formatter_url] = compiled_regex
    return url_pids, ext_id_pids_to_urls


def gather_target_ids(entity, catalog, catalog_pid, aggregated):
    catalog_constants = _get_catalog_constants(catalog)
    LOGGER.info('Gathering Wikidata items with %s identifiers ...', catalog)
    query_type = constants.IDENTIFIER, constants.HANDLED_ENTITIES.get(entity)
    for qid, target_id in sparql_queries.run_query(query_type, catalog_constants[entity]['qid'], catalog_pid, 0):
        if not aggregated.get(qid):
            aggregated[qid] = {constants.TID: set()}
        aggregated[qid][constants.TID].add(target_id)
    LOGGER.info('Got %d %s identifiers', len(aggregated), catalog)


def gather_qids(entity, catalog, catalog_pid):
    catalog_constants = _get_catalog_constants(catalog)
    LOGGER.info('Gathering Wikidata items with no %s identifiers ...', catalog)
    query_type = constants.DATASET, constants.HANDLED_ENTITIES.get(entity)
    qids = set(sparql_queries.run_query(
        query_type, catalog_constants[entity]['qid'], catalog_pid, 0))
    LOGGER.info('Got %d Wikidata items', len(qids))
    return qids


def extract_ids_from_urls(to_add, ext_id_pids_to_urls):
    LOGGER.info('Starting extraction of IDs from target links to be added ...')
    ext_ids_to_add = []
    urls_to_add = []
    for qid, urls in to_add.items():
        for url in urls:
            ext_id, pid = url_utils.get_external_id_from_url(
                url, ext_id_pids_to_urls)
            if ext_id:
                ext_ids_to_add.append((qid, pid, ext_id))
            else:
                urls_to_add.append(
                    (qid, vocabulary.DESCRIBED_AT_URL, url))
    return ext_ids_to_add, urls_to_add
