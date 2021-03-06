from ngraph.transformers.gpu.gpulayout import DimshuffleOp
from ngraph.transformers.passes.passes import GraphPass, PeepholeGraphPass
from ngraph.util.generics import generic_method
from ngraph.op_graph.op_graph import Op, tdcache
from ngraph.flex import gpuflex16


class FlexDtypePass(PeepholeGraphPass):
    @generic_method(dispatch_base_type=Op)
    def visit(self, op):
        # TODO currently hard coded gpuflex16
        op.dtype = gpuflex16


class FlexDECPass(PeepholeGraphPass):

    def __init__(self):
        self.propagate_flex_entry = False

    @generic_method(dispatch_base_type=Op)
    def visit(self, op):
        # copy flex entry for any op followed by dimshuffle op
        if self.propagate_flex_entry:
            if isinstance(op, DimshuffleOp):
                op.tensor_description().buffer.flex_entry = self.flex_entry
                self.propagate_flex_entry = False
        if op.tensor_description():
            self.propagate_flex_entry = True
            self.flex_entry = op.tensor_description().buffer.flex_entry


class ClearTensorDescriptions(GraphPass):
    def do_pass(self, ops, inits):
        tdcache.tensor_description_cache.clear()
        return ops, inits
