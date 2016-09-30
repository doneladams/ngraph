from ngraph.op_graph.arrayaxes import TensorDescription
from neon.backends.util.source_module import SourceModule
from neon.backends.layer_gpu import _get_sm_count

import numpy as np

_op_templates = {
    "assign"    : r"%(out)s = %(x)s;",
    "finite"    : None,
    "neg"       : r"%(out)s = -%(x)s;",
    "abs"       : r"%(out)s = abs(%(x)s);",
    "sqrt"      : r"%(out)s = sqrtf(%(x)s);",
    "sqr"       : r"%(out)s = %(x)s * %(x)s;",
    "exp"       : r"%(out)s = expf(%(x)s);",
    "log"       : r"%(out)s = logf(%(x)s);",
    "exp2"      : r"%(out)s = exp2f(%(x)s);",
    "log2"      : r"%(out)s = log2f(%(x)s);",
    "sig"       : r"%(out)s = 1.0f / (1.0f + expf(-%(x)s));",
    "sig2"      : r"%(out)s = 1.0f / (1.0f + exp2f(-%(x)s));",
    "tanh"      : r"%(out)s = tanhf(%(x)s);",
    "tanh2"     : r"%(out)s = (exp2f(2.0f * %(x)s) - 1.0f) / (exp2f(2.0f * %(x)s) + 1.0f);",
    "transpose" : None,
    "safelog"   : r"%(out)s = (%(x)s > 0.0f) ? logf(%(x)s) : -50.0f;",
    "add"       : r"%(out)s = %(x)s + %(y)s;",
    "sub"       : r"%(out)s = %(x)s - %(y)s;",
    "mul"       : r"%(out)s = %(x)s * %(y)s;",
    "div"       : r"%(out)s = %(x)s / %(y)s;",
    "eq"        : r"%(out)s = %(x)s == %(y)s;",
    "ne"        : r"%(out)s = %(x)s != %(y)s;",
    "lt"        : r"%(out)s = %(x)s < %(y)s;",
    "le"        : r"%(out)s = %(x)s <= %(y)s;",
    "gt"        : r"%(out)s = %(x)s > %(y)s;",
    "ge"        : r"%(out)s = %(x)s >= %(y)s;",
    "pow"       : r"%(out)s = powf(%(x)s, %(y)s);",
    "minimum"   : r"%(out)s = fminf(%(x)s, %(y)s);",
    "maximum"   : r"%(out)s = fmaxf(%(x)s, %(y)s);",
    "dot"       : None
}

_redop_templates = {
    "sum"    : r"%(out)s = %(out)s + %(x)s;",
    "max"    : r"%(out)s = fmaxf(%(out)s, %(x)s);",
    "min"    : r"%(out)s = fminf(%(out)s, %(x)s);",
    "argmax" : r"if(%(x)s > %(y)s) {%(out)s = %(index)s; %(y)s = %(x)s;}",
    "argmin" : r"if(%(x)s < %(y)s) {%(out)s = %(index)s; %(y)s = %(x)s;}"
}

_redop32_templates = {
    "sum"    : r"%(out)s = %(out)s + __shfl_xor(%(out)s, i);",
    "max"    : r"%(out)s = fmaxf(%(out)s, __shfl_xor(%(out)s, i));",
    "min"    : r"%(out)s = fminf(%(out)s, __shfl_xor(%(out)s, i));",
    "argmax" : r"""temp_idx = __shfl_xor(%(out)s, i);
%(indent)stemp_val = __shfl_xor(%(y)s, i);
%(indent)sif(temp_val > %(y)s) {%(out)s = temp_idx; %(y)s = temp_val;}""",
    "argmin" : r"""temp_idx = __shfl_xor(%(out)s, i);
%(indent)stemp_val = __shfl_xor(%(y)s, i);
%(indent)sif(temp_val < %(y)s) {%(out)s = temp_idx; %(y)s = temp_val;}""",
}

_redop_inits = {
    "sum"    : "0.0f",
    "max"    : "-FLT_MAX",
    "min"    : "FLT_MAX",
    "argmax" : "0",
    "argmin" : "0"
}

_item_loop_template = "for(int item = idx%(loopidx)s; item < loopmax; item += blockDim.x)"

_index_template1 = r"%(index)s = %(item)s * %(stridea)s;"
_index_template20 = r"%(index)s = %(item)s * %(stridea)s + idx1 * %(strideb)s;"
_index_template21 = r"%(index)s = idx0 * %(stridea)s + %(item)s * %(strideb)s;"
_index_template30 = r"%(index)s = %(item)s * %(stridea)s + idx1 * %(strideb)s + idx2 * %(stridec)s;"
_index_template31 = r"%(index)s = idx0 * %(stridea)s + %(item)s * %(strideb)s + idx2 * %(stridec)s;"
_index_template32 = r"%(index)s = idx0 * %(stridea)s + idx1 * %(strideb)s + %(item)s * %(stridec)s;"

_load_template = r"%(out)s = %(buffer)s[%(index)s];"

_store_template = r"%(buffer)s[%(index)s] = %(val)s;"

_redstore_template = r"if(idx%(loopidx)s == 0) {%(buffer)s[%(index)s] = %(val)s;}"

_red32_template = r"""
    #pragma unroll
    for (int i = 16; i > 0; i >>= 1)
    {
        %(statement)s
    }
"""

_red_template = r"""
    // Reduce within warp
    #pragma unroll
    for (int i = 16; i > 0; i >>= 1)
    {
        %(statement)s
    }
    if (!(threadIdx.x & 0x1f))
    {
        %(shared_buffer)s[threadIdx.x >> 5] = %(out)s;
    }

    __syncthreads();

    // Reduce between warps (max of 32 warps since block has max 1024 threads)
    if (threadIdx.x < 32)
    {
        %(out)s = %(shared_buffer)s[threadIdx.x];

        #pragma unroll
        for (int i = 16; i > 0; i >>= 1)
        {
            %(statement)s
        }
    }

    if (threadIdx.x == 0)
    {
        %(shared_buffer)s[0] = %(out)s;
    }

    __syncthreads();

    %(out)s = %(shared_buffer)s[0];
"""

_reg_decl_template = r"""
    %(type)s %(regname)s = %(initval)s;"""

_smem_decl_template = r"""
    __shared__ float %(sbuf)s[32];"""

_smem_init_template = r"""
        %(sbuf)s[threadIdx.x] = 0.0f;"""

_thread_index_template1 = r"""unsigned int idx0 = threadIdx.%(dim0)s + blockIdx.%(dim0)s * ITEMS_PER_BLOCK0;
    unsigned int loopmax = min(shape%(loop_axis)s, (blockIdx.x + 1) * ITEMS_PER_BLOCK0);
"""

_thread_index_template2 = r"""unsigned int idx0 = threadIdx.%(dim0)s + blockIdx.%(dim0)s * ITEMS_PER_BLOCK0;
    unsigned int idx1 = threadIdx.%(dim1)s + blockIdx.%(dim1)s * ITEMS_PER_BLOCK1;
    unsigned int loopmax = min(shape%(loop_axis)s, (blockIdx.x + 1) * ITEMS_PER_BLOCK0);
"""

_thread_index_template3 = r"""unsigned int idx0 = threadIdx.%(dim0)s + blockIdx.%(dim0)s * ITEMS_PER_BLOCK0;
    unsigned int idx1 = threadIdx.%(dim1)s + blockIdx.%(dim1)s * ITEMS_PER_BLOCK1;
    unsigned int idx2 = threadIdx.%(dim2)s + blockIdx.%(dim2)s * ITEMS_PER_BLOCK2;
    unsigned int loopmax = min(shape%(loop_axis)s, (blockIdx.x + 1) * ITEMS_PER_BLOCK0);
"""

_init_template = r"""%(smem_decl)s

    %(index_calc)s
    unsigned int index = 0;
    %(reg_decl)s
    if (threadIdx.x < 32)
    {%(smem_init)s
    }
"""

_init_template_noshare = r"""
    %(index_calc)s
    unsigned int index = 0;
    %(reg_decl)s
"""

_defines_template1 = r"""#define ITEMS_PER_BLOCK0 %(blksize0)s
"""

_defines_template2 = r"""#define ITEMS_PER_BLOCK0 %(blksize0)s
#define ITEMS_PER_BLOCK1 %(blksize1)s
"""

_defines_template3 = r"""#define ITEMS_PER_BLOCK0 %(blksize0)s
#define ITEMS_PER_BLOCK1 %(blksize1)s
#define ITEMS_PER_BLOCK2 %(blksize2)s
"""

_header_template = r"""#include <float.h>

%(defines)s
__global__ void %(kernel_name)s(%(args)s)
{"""

MAX_AXES = 3
THREADS_PER_BLOCK = 1024


class TensorDescriptionWrapper:
    def __init__(self, tensor_description, max_dims):
        self.dtype = tensor_description.dtype
        self.strides = tensor_description.strides
        self.shape = tensor_description.shape
        self.td = tensor_description

        if len(self.strides) == 0:
            self.strides = (0, )

        if len(self.shape) == 0:
            self.shape = (1, )

        if len(self.shape) < max_dims:
            self.shape = tuple([1] + list(self.shape))
            self.strides = tuple([0] + list(self.strides))


def _is_buffer(value):
    if isinstance(value, TensorDescriptionWrapper) and value.td.buffer is not None:
        return True

    return False

def _compress_axes(ops):
    reduction_axis = None
    num_axes = 0

    # Find reduction axis if reduction ops are part of this function
    for op in ops:
        if op[0] in _redop_templates:
            assert reduction_axis is None or reduction_axis == op[4]
            reduction_axis = op[4]

        for t in op[1:4]:
            if _is_buffer(t):
                num_axes = max(num_axes, len(t.shape))

    if num_axes <= 3:
        return ops

    # Combine non-reduction axes
    if reduction_axis == 0 or reduction_axis is None:
        new_axes = [[0], range(1, num_axes)]
    elif reduction_axis == (num_axes - 1):
        new_axes = [range(num_axes - 1), [num_axes - 1]]
    else:
        new_axes = [range(reduction_axis), [reduction_axis], range(reduction_axis + 1, num_axes)]

    # Reshape tensors
    new_ops = []
    for op in ops:
        new_op = list(op)

        for index in range(1, 4):
            if _is_buffer(op[index]):
                new_shape = [np.prod([t.shape[d] for d in compress]) for compress in new_axes]
                new_op[index] = op[index].reshape(tuple(new_shape))

        new_ops.append(tuple(new_op))

    return new_ops

def _optimize_loop_axis(dim):
    sm_count = _get_sm_count()

    griddim = min(sm_count, -((-dim) // 32))
    items_per_block = -((-dim) // griddim)

    items_per_thread = 1
    warps = -((-items_per_block) // (32 * items_per_thread))

    while (warps > 4 and items_per_thread < 8) or (warps > 32):
        items_per_thread = items_per_thread + 1
        warps = -((-items_per_block) // (32 * items_per_thread))

    blockdim = warps * 32

    return (griddim, blockdim, items_per_thread)

def _get_axes_mapping(ops):
    max_shape = [1] * MAX_AXES
    axes = range(MAX_AXES)
    reduction_axis = None

    # Find maximum shape and check for reductions
    for op in ops:
        if op[0] in _redop_templates:
            assert reduction_axis is None or reduction_axis == op[4]
            reduction_axis = op[4]

        for t in op[1:4]:
            if _is_buffer(t):
                shape = t.shape
                assert len(shape) <= MAX_AXES

                for axis in axes:
                    if axis < len(shape) and shape[axis] > max_shape[axis]:
                        max_shape[axis] = shape[axis]

    # Determine which axis/axes map to block
    axes_mapping = [(None, None, None, None, None)] * MAX_AXES
    dims = ['x', 'y', 'z']
    blocksize = 1
    if reduction_axis is not None:
        blockdim = -((-max_shape[reduction_axis]) // 256)
        blockdim = min(THREADS_PER_BLOCK, max(32, blockdim * 32))
        items_per_thread = -((-max_shape[reduction_axis]) // blockdim)
        axes_mapping[reduction_axis] = ('x', blockdim, 1, items_per_thread, max_shape[reduction_axis])

        blocksize = blockdim
        dims.remove('x')
    elif max_shape[0] == 1 and np.prod(max_shape) != 1:
        if max_shape[1] == 1:
            axis = 2
        else:
            axis = 1

        (griddim, blockdim, items_per_thread) = _optimize_loop_axis(max_shape[axis])
        blocksize = blockdim
        axes_mapping[axis] = (dims.pop(0), blockdim, griddim, items_per_thread, max_shape[axis])

    # TODO: consider contiguity in axis mapping
    for axis in axes:
        if axes_mapping[axis][0] is not None:
            continue

        if len(dims) == MAX_AXES:
            (griddim, blockdim, items_per_thread) = _optimize_loop_axis(max_shape[axis])
            blocksize = blockdim
        else:
            items_per_thread = 1
            blockdim = 1
            while (blockdim * blocksize * 2) <= THREADS_PER_BLOCK and (blockdim * 2) < max_shape[axis]:
                blockdim = blockdim * 2
            blocksize = blocksize * blockdim
            griddim = -((-max_shape[axis]) // (blockdim * items_per_thread))

        axes_mapping[axis] = (dims.pop(0), blockdim, griddim, items_per_thread, max_shape[axis])

    # Prune unused axes
    dims = MAX_AXES
    while (axes_mapping[dims - 1][1] * axes_mapping[dims - 1][2] * axes_mapping[dims - 1][3]) == 1:
        dims = dims - 1

    return (axes_mapping, dims)

def _preprocess_ops(ops):
    updaters = {}
    dependencies = {}

    out_ops = [[]]
    last_evaluated_stage = {}

    def add_dep(dep_index):
        for dep in dependencies[dep_index]:
            if dep not in last_evaluated_stage or last_evaluated_stage[dep] != (len(out_ops) - 1):
                if ops[dep][0] not in _redop_templates:
                    add_dep(dep)

        out_ops[-1].append(ops[dep_index])
        last_evaluated_stage[dep_index] = len(out_ops) - 1

    # Find dependencies for each operation
    for op, index in zip(ops, range(len(ops))):
        dependencies[index] = []

        for inval in op[1:3]:
            if inval is not None and inval in updaters:
                dependencies[index].append(updaters[inval])

        updaters[op[3]] = index

    # Replicate any ops where dependencies cross boundary of a reduction
    for op, index in zip(ops, range(len(ops))):
        if op[0] in _op_templates:
            if out_ops[-1] and out_ops[-1][-1][0] in _redop_templates:
                # New stage
                out_ops.append([])

        # Check that op's dependencies are evaluated in this stage
        add_dep(index)

    return out_ops

def _get_register_type(dtype):
    if dtype == np.float32 or dtype == np.float16:
        return "float"
    elif dtype == np.int32:
        return "int"
    else:
        raise TypeError("Unsupported type")

def _wrap_tensor_descriptions(ops):
    new_ops = []
    max_dims = 1
    for op in ops:
        new_op = list(op)
        for index in range(1, 4):
            if isinstance(new_op[index], TensorDescription):
                max_dims = max(max_dims, len(new_op[index].shape))
                new_op[index] = TensorDescriptionWrapper(new_op[index], max_dims)

        new_ops.append(tuple(new_op))

    return new_ops

def _get_compound_kernel(ops, axes_mapping, dims):
    # Find axis which thread will loop over
    loop_axis = 0
    for axis in range(len(axes_mapping)):
        if axes_mapping[axis][0] == 'x':
            loop_axis = axis

    # Choose templates based on number of axes
    if dims == 1:
        _defines_template = _defines_template1
        _index_template = _index_template1
        _thread_index_template = _thread_index_template1
    elif dims == 2:
        _defines_template = _defines_template2
        if loop_axis == 0:
            _index_template = _index_template20
        else:
            _index_template = _index_template21
        _thread_index_template = _thread_index_template2
    elif dims == 3:
        _defines_template = _defines_template3
        if loop_axis == 0:
            _index_template = _index_template30
        elif loop_axis == 1:
            _index_template = _index_template31
        else:
            _index_template = _index_template32
        _thread_index_template = _thread_index_template3
    else:
        assert False

    # Pre-process ops so that we don't need to store intermediate results in registers
    stages = _preprocess_ops(ops)

    # Build lists of registers for each input/output
    register_mapping = {None : "None"}
    reg_count = 0
    register_inits = {}
    register_types = {}
    buffers = {}
    last_write = {}
    constants = {}
    has_argmaxmin = False

    for stage, stage_index in zip(stages, range(len(stages))):
        for op, op_index in zip(stage, range(len(stage))):
            if op[0] == "argmin" or op[0] == "argmax":
                has_argmaxmin = True

            for inval in op[1:3]:
                if inval not in register_mapping:
                    if isinstance(inval, (np.float16, np.float32, np.float64)):
                        regname = "constant" + str(len(constants))
                        register_mapping[inval] = regname
                        constants[regname] = inval
                        register_types[regname] = _get_register_type(type(inval))
                    else:
                        regname = "reg" + str(reg_count)
                        reg_count = reg_count + 1
                        register_mapping[inval] = regname
                        register_types[regname] = _get_register_type(inval.dtype)
                        if (op[0] == "argmax" or op[0] == "argmin") and inval is op[2]:
                            register_inits[regname] = "FLT_MAX" if op[0] == "argmin" else "-FLT_MAX"
                        else:
                            register_inits[regname] = "0.0f"

                        if _is_buffer(inval):
                            buffername = "buf" + str(len(buffers))
                            buffers[inval] = buffername

            if op[3] not in register_mapping:
                regname = "reg" + str(reg_count)
                reg_count = reg_count + 1
                register_mapping[op[3]] = regname

                register_types[regname] = _get_register_type(op[3].dtype)
                if op[0] in _redop_templates:
                    register_inits[regname] = _redop_inits[op[0]]
                else:
                    register_inits[regname] = "0.0f"

                if _is_buffer(op[3]):
                    buffername = "buf" + str(len(buffers))
                    buffers[op[3]] = buffername

            if _is_buffer(op[3]):
                last_write[op[3]] = (stage_index, op_index)

    buffers_in_reg = [set() for stage in stages]
    code = ""
    arg_desc = ""
    indent_str = "    "
    shared_buffers = []
    for stage, stage_index in zip(stages, range(len(stages))):
        # Collect all load, op, and store statements for this stage
        broadcast_loads = []
        reduction_stores = []
        loop_loads = []
        loop_stores = []
        op_statements = []
        warp_reductions = []
        for op, op_index in zip(stage, range(len(stage))):
            for inval in op[1:3]:
                if _is_buffer(inval) and inval not in buffers_in_reg[stage_index]:
                    load_code = _load_template % {
                        "index"   : "index",
                        "out"     : register_mapping[inval],
                        "buffer"  : buffers[inval]
                    }

                    if inval.strides[loop_axis] == 0 or inval.shape[loop_axis] == 1:
                        index_code = _index_template % {
                            "index"   : "index",
                            "stridea" : "stridea_" + buffers[inval],
                            "strideb" : "strideb_" + buffers[inval],
                            "stridec" : "stridec_" + buffers[inval],
                            "item"    : "idx" + str(loop_axis)
                        }
                        broadcast_loads.append(index_code)
                        broadcast_loads.append(load_code)
                    else:
                        index_code = _index_template % {
                            "index"   : "index",
                            "stridea" : "stridea_" + buffers[inval],
                            "strideb" : "strideb_" + buffers[inval],
                            "stridec" : "stridec_" + buffers[inval],
                            "item"    : "item"
                        }
                        loop_loads.append(index_code)
                        loop_loads.append(load_code)

                    buffers_in_reg[stage_index].add(inval)

            if op[0] in _op_templates:
                op_code = _op_templates[op[0]] % {
                    "x" : register_mapping[op[1]],
                    "y" : register_mapping[op[2]],
                    "out" : register_mapping[op[3]]
                }
            else:
                op_code = _redop_templates[op[0]] % {
                    "x"     : register_mapping[op[1]],
                    "y"     : register_mapping[op[2]],
                    "out"   : register_mapping[op[3]],
                    "index" : "item"
                }
                redop_code = _redop32_templates[op[0]] % {
                    "out"    : register_mapping[op[3]],
                    "y"      : register_mapping[op[2]],
                    "indent" : (2 * indent_str)
                }
                if axes_mapping[loop_axis][1] <= 32:
                    warp_red_code = _red32_template % {
                        "statement" : redop_code
                    }
                else:
                    sbuf = "sbuffer" + str(len(shared_buffers))
                    shared_buffers.append(sbuf)
                    warp_red_code = _red_template % {
                        "statement"     : redop_code,
                        "out"           : register_mapping[op[3]],
                        "shared_buffer" : sbuf
                    }

                warp_reductions.append(warp_red_code)

            op_statements.append(op_code)

            if _is_buffer(op[3]):
                buffers_in_reg[stage_index].add(op[3])
                if op[0] in _redop_templates:
                    for subsequent_stage in buffers_in_reg[stage_index+1:]:
                        subsequent_stage.add(op[3])

                if last_write[op[3]] == (stage_index, op_index):
                    if op[0] in _redop_templates or op[3].strides[loop_axis] == 0 or op[3].shape[loop_axis] == 1:
                        store_code = _redstore_template % {
                            "index"   : "index",
                            "val"     : register_mapping[op[3]],
                            "buffer"  : buffers[op[3]],
                            "loopidx" : loop_axis
                        }
                        index_code = _index_template % {
                            "index"   : "index",
                            "stridea" : "stridea_" + buffers[op[3]],
                            "strideb" : "strideb_" + buffers[op[3]],
                            "stridec" : "stridec_" + buffers[op[3]],
                            "item"    : "idx" +  str(loop_axis)
                        }
                        reduction_stores.append(index_code)
                        reduction_stores.append(store_code)
                    else:
                        store_code = _store_template % {
                            "index"   : "index",
                            "val"     : register_mapping[op[3]],
                            "buffer"  : buffers[op[3]]
                        }
                        index_code = _index_template % {
                            "index"   : "index",
                            "stridea" : "stridea_" + buffers[op[3]],
                            "strideb" : "strideb_" + buffers[op[3]],
                            "stridec" : "stridec_" + buffers[op[3]],
                            "item"    : "item"
                        }
                        loop_stores.append(index_code)
                        loop_stores.append(store_code)

        # Build stage code from collected statements
        # Add broadcast loads
        for load in broadcast_loads:
            code = code + "\n" + indent_str + load

        # Add op statements
        if len(loop_loads) == 0 and len(loop_stores) == 0:
            # All tensors are reduced, no item loop needed
            for statement in op_statements:
                code = code + "\n" + indent_str + statement
        else:
            # Build item loop
            item_loop_code = _item_loop_template % {
                "loopidx" : loop_axis
            }
            code = code + "\n" + indent_str + item_loop_code + "\n" + indent_str + "{"

            for load in loop_loads:
                code = code + "\n" + (indent_str * 2) + load

            for statement in op_statements:
                code = code + "\n" + (indent_str * 2) + statement

            for store in loop_stores:
                code = code + "\n" + (indent_str * 2) + store

            code = code + "\n" + indent_str + "}"

        # Add warp reductions
        for warp_red in warp_reductions:
            code = code + warp_red

        # Add reduction stores
        for store in reduction_stores:
            code = code + "\n" + indent_str + store

    # Construct kernel name
    kernel_name = "float_ew_"
    if len(ops) > 4:
        op_names = [op[0] for op in ops[:5]]
    else:
        op_names = [op[0] for op in ops]
    kernel_name = kernel_name + '_'.join(op_names)

    # List arguments to kernel
    args = ["unsigned int shapea"]
    arg_desc = "I"
    params = [axes_mapping[0][4]]
    if dims == 2:
        args.append("unsigned int shapeb")
        arg_desc = arg_desc + "I"
        params.append(axes_mapping[1][4])
    elif dims == 3:
        args.extend(["unsigned int shapeb", "unsigned int shapec"])
        arg_desc = arg_desc + "II"
        params.extend([axes_mapping[1][4], axes_mapping[2][4]])

    for constant in constants.keys():
        args.append("float " + constant)
        arg_desc = arg_desc + "f"
        params.append(constants[constant])

    for buf in buffers.keys():
        args.append(_get_register_type(buf.dtype) + "* " + buffers[buf])
        args.append("unsigned int stridea_" + buffers[buf])
        arg_desc = arg_desc + "PI"
        params.append(buf.td)
        params.append(buf.strides[0] // buf.dtype.itemsize)

        if dims == 2:
            args.append("unsigned int strideb_" + buffers[buf])
            arg_desc = arg_desc + "I"
            params.append(buf.strides[1] // buf.dtype.itemsize)
        elif dims == 3:
            args.append("unsigned int strideb_" + buffers[buf])
            args.append("unsigned int stridec_" + buffers[buf])
            arg_desc = arg_desc + "II"
            params.append(buf.strides[1] // buf.dtype.itemsize)
            params.append(buf.strides[2] // buf.dtype.itemsize)

    argstring = ', '.join(args)

    # Construct header
    defines = _defines_template % {
        "blksize0" : axes_mapping[0][1] * axes_mapping[0][3],
        "blksize1" : axes_mapping[1][1] * axes_mapping[1][3],
        "blksize2" : axes_mapping[2][1] * axes_mapping[2][3]
    }

    header = _header_template % {
        "defines"     : defines,
        "kernel_name" : kernel_name,
        "args"        : argstring
    }

    # Initialization code
    reg_decls = ""
    for reg in register_mapping.values():
        if reg != "None" and reg not in constants:
            reg_decls = reg_decls + _reg_decl_template % {
                "regname" : reg,
                "initval" : register_inits[reg],
                "type"    : register_types[reg]
            }

    if has_argmaxmin:
        reg_decls = reg_decls + "\n    float temp_val = 0.0f;"
        reg_decls = reg_decls + "\n    unsigned int temp_idx = 0;"

    smem_decls = ""
    smem_inits = ""
    for sbuf in shared_buffers:
        smem_decls = smem_decls + _smem_decl_template % {
            "sbuf" : sbuf
        }
        smem_inits = smem_inits + _smem_init_template % {
            "sbuf" : sbuf
        }

    loop_axis_letters = ['a', 'b', 'c']
    index_calc = _thread_index_template % {
        "dim0"      : axes_mapping[0][0],
        "dim1"      : axes_mapping[1][0],
        "dim2"      : axes_mapping[2][0],
        "loop_axis" : loop_axis_letters[loop_axis]
    }

    if shared_buffers:
        code = _init_template % {
            "smem_decl"  : smem_decls,
            "reg_decl"   : reg_decls,
            "smem_init"  : smem_inits,
            "index_calc" : index_calc
        } + code
    else:
        code = _init_template_noshare % {
            "reg_decl"   : reg_decls,
            "index_calc" : index_calc
        } + code

    code = header + code + "\n}"

    # import pdb; pdb.set_trace()
    module = SourceModule(code, options=[])
    kernel = module.get_function(kernel_name)
    kernel.name = kernel_name
    kernel.prepare(arg_desc)

    return (kernel, params)

def _call_compound_kernel(ops):
    # Take care of 0d tensors
    ops = _wrap_tensor_descriptions(ops)

    ops = _compress_axes(ops)

    (axes_mapping, dims) = _get_axes_mapping(ops)

    kernel, params = _get_compound_kernel(ops, axes_mapping, dims)

    # Calculate block and grid dims
    blockdim = [1, 1, 1]
    griddim = [1, 1, 1]
    for axis in axes_mapping:
        if axis[0] == 'x':
            blockdim[0] = axis[1]
            griddim[0] = axis[2]
        elif axis[0] == 'y':
            blockdim[1] = axis[1]
            griddim[1] = axis[2]
        elif axis[0] == 'z':
            blockdim[2] = axis[1]
            griddim[2] = axis[2]

    kernel.prepared_async_call(tuple(griddim), tuple(blockdim), None, *params, shared_size=128)

def _prepare_compound_kernel(ops):
    # Take care of 0d tensors
    ops = _wrap_tensor_descriptions(ops)

    ops = _compress_axes(ops)

    (axes_mapping, dims) = _get_axes_mapping(ops)

    kernel, params = _get_compound_kernel(ops, axes_mapping, dims)

    # Calculate block and grid dims
    blockdim = [1, 1, 1]
    griddim = [1, 1, 1]
    for axis in axes_mapping:
        if axis[0] == 'x':
            blockdim[0] = axis[1]
            griddim[0] = axis[2]
        elif axis[0] == 'y':
            blockdim[1] = axis[1]
            griddim[1] = axis[2]
        elif axis[0] == 'z':
            blockdim[2] = axis[1]
            griddim[2] = axis[2]

    params = [tuple(griddim), tuple(blockdim), None] + params
    return (kernel, params, 128)
