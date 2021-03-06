# ----------------------------------------------------------------------------
# Copyright 2016 Nervana Systems Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------------

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import numpy as np
from ngraph.frontends.tensorflow.tests.importer_tester import ImporterTester
import pytest


@pytest.mark.transformer_dependent
class Tester(ImporterTester):
    def test_relu_grad(self):
        # random number
        a = tf.constant(
            np.random.randn(1, 10).astype(np.float32), dtype=tf.float32)
        b = tf.constant(np.ones((10, 1)).astype(np.float32), dtype=tf.float32)
        f = tf.matmul(tf.nn.relu(a), b)
        a_grad = tf.gradients(f, a)[0]
        self.run(a_grad, tf_feed_dict={})

        # zeros
        a = tf.constant(np.zeros((1, 10)).astype(np.float32), dtype=tf.float32)
        b = tf.constant(np.ones((10, 1)).astype(np.float32), dtype=tf.float32)
        f = tf.matmul(tf.nn.relu(a), b)
        a_grad = tf.gradients(f, a)[0]
        self.run(a_grad, tf_feed_dict={})
