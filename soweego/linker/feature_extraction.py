#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Set of techniques to compare record pairs (read extract features) for probabilistic linking."""

__author__ = 'Marco Fossati'
__email__ = 'fossati@spaziodati.eu'
__version__ = '1.0'
__license__ = 'GPL-3.0'
__copyright__ = 'Copyleft 2018, Hjfocs'

import logging

import jellyfish
import numpy as np
import pandas as pd
from recordlinkage.base import BaseCompareFeature
from recordlinkage.utils import fillna
from sklearn.feature_extraction.text import CountVectorizer

from soweego.commons import text_utils

LOGGER = logging.getLogger(__name__)

# Adapted from https://github.com/J535D165/recordlinkage/blob/master/recordlinkage/compare.py
# See RECORDLINKAGE_LICENSE


class StringList(BaseCompareFeature):

    name = 'string_list'
    description = 'Compare pairs of lists with string values'

    def __init__(self,
                 left_on,
                 right_on,
                 algorithm='levenshtein',
                 threshold=None,
                 missing_value=0.0,
                 analyzer=None,
                 ngram_range=(2, 2),
                 label=None):
        super(StringList, self).__init__(left_on, right_on, label=label)
        self.algorithm = algorithm
        self.threshold = threshold
        self.missing_value = missing_value
        self.analyzer = analyzer
        self.ngram_range = ngram_range

    def _compute_vectorized(self, source_column, target_column):
        if self.algorithm == 'levenshtein':
            algorithm = self.levenshtein_similarity
        elif self.algorithm == 'cosine':
            algorithm = self.cosine_similarity
        else:
            raise ValueError(
                'Bad string similarity algorithm: %s. Please use one of %s' % (self.algorithm, ('levenshtein', 'cosine')))

        compared = algorithm(source_column, target_column)
        compared_filled = fillna(compared, self.missing_value)

        if self.threshold is None:
            return compared_filled
        return (compared_filled >= self.threshold).astype(np.float64)

    # Adapted from https://github.com/J535D165/recordlinkage/blob/master/recordlinkage/algorithms/string.py
    # Average the edit distance among the list of values
    # TODO low scores if name is swapped with surname, see https://github.com/Wikidata/soweego/issues/175
    def levenshtein_similarity(self, source_column, target_column):
        paired = pd.Series(list(zip(source_column, target_column)))

        def _levenshtein_apply(pair):
            source_values, target_values = pair
            if not all(pair) or source_values is np.nan or target_values is np.nan:
                LOGGER.warning(
                    "Can't compute Levenshtein distance, the pair contains null values: %s", pair)
                return np.nan

            scores = []

            # Paranoid checks to ensure we work on lists
            if isinstance(source_values, str):
                source_values = [source_values]
            if isinstance(target_values, str):
                target_values = [target_values]

            for source in source_values:
                for target in target_values:
                    try:
                        score = 1 - jellyfish.levenshtein_distance(source, target) \
                            / np.max([len(source), len(target)])
                        scores.append(score)
                    except TypeError:
                        if pd.isnull(source) or pd.isnull(target):
                            scores.append(self.missing_value)
                        else:
                            raise
            avg = np.average(scores)
            return avg

        return paired.apply(_levenshtein_apply)

    # TODO move this method to another class: the measure doesn't actually work on LISTS, it assumes joined descriptions as per workflow#_join_descriptions
    def cosine_similarity(self, source_column, target_column):
        if len(source_column) != len(target_column):
            raise ValueError('Columns must have the same length')
        if len(source_column) == len(target_column) == 0:
            LOGGER.warning(
                "Can't compute cosine similarity, columns are empty")
            return pd.Series(np.nan)

        # No analyzer means input underwent commons.text_utils#tokenize
        if self.analyzer is None:
            vectorizer = CountVectorizer(analyzer=str.split)
        elif self.analyzer == 'soweego':
            vectorizer = CountVectorizer(analyzer=text_utils.tokenize)
        # scikit-learn built-ins
        # 'char' and char_wb' make CHARACTER n-grams, instead of WORD ones, may be useful for short strings with misspellings.
        # 'char_wb' makes n-grams INSIDE words, thus eventually padding with whitespaces.
        # See https://scikit-learn.org/stable/modules/feature_extraction.html#limitations-of-the-bag-of-words-representation
        elif self.analyzer in ('word', 'char', 'char_wb'):
            vectorizer = CountVectorizer(
                analyzer=self.analyzer, strip_accents='unicode', ngram_range=self.ngram_range)
        else:
            raise ValueError(
                'Bad text analyzer: %s. Please use one of %s' % (self.analyzer, ('soweego', 'word', 'char', 'char_wb')))

        data = source_column.append(target_column).fillna('')
        try:
            vectors = vectorizer.fit_transform(data)
        except ValueError as ve:
            LOGGER.warning(
                'Failed transforming text into vectors, reason: %s. Text: %s', ve, data)
            return pd.Series(np.nan)

        def _metric_sparse_cosine(u, v):
            a = np.sqrt(u.multiply(u).sum(axis=1))
            b = np.sqrt(v.multiply(v).sum(axis=1))
            ab = v.multiply(u).sum(axis=1)
            cosine = np.divide(ab, np.multiply(a, b)).A1
            return cosine

        return _metric_sparse_cosine(vectors[:len(source_column)], vectors[len(source_column):])


class UrlList(BaseCompareFeature):

    name = 'url_list'
    description = 'Compare pairs of lists with URL values'

    def __init__(self, left_on, right_on, agree_value=1.0, disagree_value=0.0, missing_value=0.0, label=None):
        super(UrlList, self).__init__(left_on, right_on, label=label)
        self.agree_value = agree_value
        self.disagree_value = disagree_value
        self.missing_value = missing_value

    def _compute_vectorized(self, source_column, target_column):
        concatenated = pd.Series(list(zip(source_column, target_column)))

        def exact_apply(pair):
            source_urls, target_urls = pair

            if not all(pair) or source_urls is np.nan or target_urls is np.nan:
                LOGGER.debug(
                    "Can't compare URLs, the pair contains null values: %s", pair)
                return np.nan

            scores = []
            for source in source_urls:
                for target in target_urls:
                    if pd.isnull(source) or pd.isnull(target):
                        scores.append(self.missing_value)
                        continue
                    if source == target:
                        scores.append(self.agree_value)
                    else:
                        scores.append(self.disagree_value)
            return np.average(scores)

        return fillna(concatenated.apply(exact_apply), self.missing_value)
