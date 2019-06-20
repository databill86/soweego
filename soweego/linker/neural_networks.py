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
from contextlib import redirect_stderr

import pandas as pd
from recordlinkage.adapters import KerasAdapter
from recordlinkage.base import BaseClassifier

from soweego.commons import constants

with redirect_stderr(open(os.devnull, "w")):
    # When the keras module is initialized it will print a message to `stderr`
    # saying which backend it is using. To avoid this behavior we
    # redirect stderr to `devnull` for the statements in this block.
    from keras.callbacks import EarlyStopping, ModelCheckpoint, TensorBoard
    from keras.layers import BatchNormalization, Dense
    from keras.models import Sequential

LOGGER = logging.getLogger(__name__)


class _BaseNN(KerasAdapter, BaseClassifier):
    """
    This class implements the fit method, which is common to all
    NN implementations.
    """

    def _fit(self,
             features: pd.Series,
             answers: pd.Series,
             batch_size: int = constants.BATCH_SIZE,
             epochs: int = constants.EPOCHS,
             validation_split: float = constants.VALIDATION_SPLIT
             ) -> None:
        """
        Trains the NN using the specified arguments

        :param features: are the training points that will be fed to the network
        :param answers: are the correct predictions for each training point
        :param batch_size: t
        :param epochs:
        :param validation_split:
        :return:
        """

        tensor_path = os.path.join(
            constants.SHARED_FOLDER, constants.TENSOR_BOARD
        )
        model_path = os.path.join(
            constants.SHARED_FOLDER,
            constants.NEURAL_NETWORK_CHECKPOINT_MODEL % self.__class__.__name__,
        )
        os.makedirs(os.path.dirname(tensor_path), exist_ok=True)
        os.makedirs(os.path.dirname(model_path), exist_ok=True)

        # when fitting create a record of our training process
        history = self.kernel.fit(
            x=features,
            y=answers,
            validation_split=validation_split,
            batch_size=batch_size,
            epochs=epochs,
            callbacks=[
                EarlyStopping(monitor='val_loss',
                              patience=100,
                              verbose=2,
                              restore_best_weights=True),

                ModelCheckpoint(model_path, save_best_only=True),

                TensorBoard(log_dir=tensor_path),
            ]
        )

        # print parameters
        LOGGER.info('Fit parameters: %s', history.params)

    def __repr__(self):
        return f'{self.__class__.__name__}(optimizer={self.kernel.optimizer.__class__.__name__}, loss={self.kernel.loss}, metrics={self.kernel.metrics}, config={self.kernel.get_config()})'


class SingleLayerPerceptron(_BaseNN):
    """A single-layer perceptron classifier."""

    def __init__(self, input_dim, **kwargs):
        super(SingleLayerPerceptron, self).__init__()

        model = Sequential()
        model.add(
            Dense(1, input_dim=input_dim, activation=constants.ACTIVATION)
        )
        model.compile(
            optimizer=kwargs.get('optimizer', constants.OPTIMIZER),
            loss=constants.LOSS,
            metrics=constants.METRICS,
        )

        self.kernel = model


class MultiLayerPerceptron(_BaseNN):
    """A multi-layer perceptron classifier."""

    def __init__(self, input_dimension):
        super(MultiLayerPerceptron, self).__init__()

        model = Sequential(
            [
                Dense(128, input_dim=input_dimension, activation='relu'),
                BatchNormalization(),
                Dense(32, activation='relu'),
                BatchNormalization(),
                Dense(1, activation='sigmoid'),
            ]
        )

        model.compile(
            optimizer='adadelta',
            loss='binary_crossentropy',
            metrics=['accuracy'],
        )

        self.kernel = model
