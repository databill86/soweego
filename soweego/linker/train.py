#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Training set construction for supervised linking."""

__author__ = 'Marco Fossati'
__email__ = 'fossati@spaziodati.eu'
__version__ = '1.0'
__license__ = 'GPL-3.0'
__copyright__ = 'Copyleft 2018, Hjfocs'

import logging
import os

import click
import recordlinkage as rl
from sklearn.externals import joblib

from soweego.commons import constants, target_database
from soweego.linker import workflow

LOGGER = logging.getLogger(__name__)


@click.command()
@click.argument('classifier', type=click.Choice(constants.CLASSIFIERS))
@click.argument('target', type=click.Choice(target_database.available_targets()))
@click.argument('target_type', type=click.Choice(target_database.available_types()))
@click.option('-b', '--binarize', default=0.1, help="Default: 0.1")
@click.option('-o', '--output-dir', type=click.Path(file_okay=False), default='/app/shared', help="Default: '/app/shared'")
def cli(classifier, target, target_type, binarize, output_dir):
    """Train a probabilistic linker."""

    model = execute(
        constants.CLASSIFIERS[classifier], target, target_type, binarize, output_dir)
    outfile = os.path.join(
        output_dir, constants.LINKER_MODEL % (target, classifier))
    joblib.dump(model, outfile)
    LOGGER.info("%s model dumped to '%s'", classifier, outfile)


def execute(classifier, catalog, entity, binarize, dir_io):
    wd_reader, target_reader = workflow.train_test_build(
        catalog, entity, dir_io)
    wd, target = workflow.preprocess('training', wd_reader, target_reader)
    candidate_pairs = workflow.train_test_block(wd, target)
    feature_vectors = workflow.extract_features(candidate_pairs, wd, target)
    return _train(classifier, feature_vectors, candidate_pairs, binarize)


def _train(classifier, feature_vectors, candidate_pairs, binarize):
    model = workflow.init_model(classifier, binarize)
    LOGGER.info('Training a %s', classifier.__name__)
    model.fit(feature_vectors, candidate_pairs)
    LOGGER.info('Training done')
    return model