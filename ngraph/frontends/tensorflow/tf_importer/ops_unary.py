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

from ngraph.frontends.tensorflow.tf_importer.ops_base import OpsBase
import ngraph as ng


class OpsUnary(OpsBase):
    """
    Mix-in class for unary ops
    """

    def _element_wise_unary(self, ng_op, tf_node, inputs):
        """
        Element-wise unary operation.

        Args:
            ng_op: ngraph Op to be applied.
            tf_node: NodeDef object, the tensorflow node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the tensorflow node.
        """
        # get inputs
        left = inputs[0]

        # result
        result_op = ng_op(left).named(tf_node.name)

        # return op
        return result_op

    def Tanh(self, tf_node, inputs):
        """
        Computes hyperbolic tangent of `x` element-wise.

        Arguments:
            tf_node: NodeDef object, the tensorflow node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the tensorflow node.

        Inputs to tf_node:
            x, name
        """
        return self._element_wise_unary(ng.tanh, tf_node, inputs)

    def Sigmoid(self, tf_node, inputs):
        """
        Computes `y = 1 / (1 + exp(-x))` element-wise.

        Arguments:
            tf_node: NodeDef object, the tensorflow node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the tensorflow node.

        Inputs to tf_node:
            x, name
        """
        return self._element_wise_unary(ng.sigmoid, tf_node, inputs)

    def Relu(self, tf_node, inputs):
        """
        Computes rectified linear: `max(features, 0)`.

        Arguments:
            tf_node: NodeDef object, the tensorflow node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the tensorflow node.

        Inputs to tf_node:
            features, name
        """
        return ng.maximum(inputs[0], 0.).named(tf_node.name)

    def Identity(self, tf_node, inputs):
        """
        Return a tensor with the same shape and contents as the input tensor or
        value.
        TODO: currently only a pass through

        Arguments:
            tf_node: NodeDef object, the tensorflow node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the tensorflow node.

        Inputs to tf_node:
            input, name
        """
        return inputs[0]

    def Log(self, tf_node, inputs):
        """
        Natural log of x element-wise.

        Arguments:
            tf_node: NodeDef object, the tensorflow node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the tensorflow node.

        Inputs to tf_node:
            x, name
        """
        return ng.log(inputs[0]).named(tf_node.name)

    def Neg(self, tf_node, inputs):
        """
        Numerical negative value element-wise.

        Arguments:
            tf_node: NodeDef object, the tensorflow node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the tensorflow node.

        Inputs to tf_node:
            x, name
        """
        return ng.negative(inputs[0]).named(tf_node.name)

    def Square(self, tf_node, inputs):
        """
        Performs the x^2 on the each element of input.

        Arguments:
            tf_node: NodeDef object, the tensorflow node to convert.
            inputs: List of ngraph Ops as inputs to this node.

        Returns:
            A ngraph Op corresponding to the tensorflow node.

        Inputs to tf_node:
            input
        """
        return ng.square(inputs[0]).named(tf_node.name)
