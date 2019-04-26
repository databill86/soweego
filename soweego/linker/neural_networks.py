#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Neural network classifiers."""

__author__ = 'Marco Fossati'
__email__ = 'fossati@spaziodati.eu'
__version__ = '1.0'
__license__ = 'GPL-3.0'
__copyright__ = 'Copyleft 2019, Hjfocs'

import logging
import os

from keras.callbacks import EarlyStopping, ModelCheckpoint, TensorBoard
from keras.layers import Dense
from keras.models import Sequential
from recordlinkage.adapters import KerasAdapter
from recordlinkage.base import BaseClassifier

from soweego.commons import constants

LOGGER = logging.getLogger(__name__)


class SingleLayerPerceptron(KerasAdapter, BaseClassifier):
    """A single-layer perceptron classifier."""

    def __init__(self, input_dimension):
        super(SingleLayerPerceptron, self).__init__()

        model = Sequential()
        model.add(Dense(1, input_dim=input_dimension, activation='sigmoid'))
        model.compile(
            optimizer='sgd',
            loss='binary_crossentropy',
            metrics=['accuracy']
        )

        self.kernel = model

    def _fit(self, features, answers, batch_size=1024, epochs=1000):
        self.kernel.fit(
            x=features,
            y=answers,
            validation_split=0.33,
            batch_size=batch_size,
            epochs=epochs,
            callbacks=[
                EarlyStopping(),
                ModelCheckpoint(
                    os.path.join(
                        constants.SHARED_FOLDER,
                        constants.NEURAL_NETWORK_CHECKPOINT_MODEL % self.__class__.__name__),
                    save_best_only=True
                ),
                TensorBoard(log_dir=constants.SHARED_FOLDER)
            ]
        )