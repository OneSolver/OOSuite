# created by Dmitrey

from numpy import inf, asfarray, copy, all, any, empty, atleast_2d, zeros, dot, asarray, atleast_1d, empty, \
ones, ndarray, where, array, nan, ix_, vstack, eye, array_equal, isscalar, diag, log, hstack, sum, prod, nonzero,\
isnan, asscalar, zeros_like, ones_like, amin, amax, logical_and, logical_or, isinf, nanmin, nanmax
from numpy.linalg import norm
from misc import FuncDesignerException, Diag, Eye, pWarn, scipyAbsentMsg, scipyInstalled, \
raise_except, DiagonalType
from copy import deepcopy
from ooPoint import ooPoint
from Interval import Interval, ZeroCriticalPoints

Copy = lambda arg: asscalar(arg) if type(arg)==ndarray and arg.size == 1 else arg.copy() if hasattr(arg, 'copy') else copy(arg)
Len = lambda x: 1 if isscalar(x) else x.size if type(x)==ndarray else len(x)

try:
    from DerApproximator import get_d1, check_d1
    DerApproximatorIsInstalled = True
except:
    DerApproximatorIsInstalled = False


try:
    import scipy
    SparseMatrixConstructor = lambda *args, **kwargs: scipy.sparse.lil_matrix(*args, **kwargs)
    from scipy import sparse
    from scipy.sparse import hstack as HstackSP, isspmatrix_csc, isspmatrix_csr, eye as SP_eye
    def Hstack(Tuple):
        ind = where([isscalar(elem) or prod(elem.shape)!=0 for elem in Tuple])[0].tolist()
        elems = [Tuple[i] for i in ind]
        if any([isspmatrix(elem) for elem in elems]):
            return HstackSP(elems)
        
        s = set([(0 if isscalar(elem) else elem.ndim) for elem in elems])
        ndim = max(s)
        if ndim <= 1:  return hstack(elems)
        assert ndim <= 2 and 1 not in s, 'bug in FuncDesigner kernel, inform developers'
        return hstack(elems) if 0 not in s else hstack([atleast_2d(elem) for elem in elems])
        
    from scipy.sparse import isspmatrix
except:
    scipy = None
    isspmatrix = lambda *args,  **kwargs:  False
    Hstack = hstack

class oofun:
    #TODO:
    #is_oovarSlice = False
    
    d = None # derivative
    input = None#[] 
    #usedIn =  set()
    is_oovar = False
    isConstraint = False
    #isDifferentiable = True
    discrete = False
    isCostly = False
    
    stencil = 3 # used for DerApproximator
    
    #TODO: modify for cases where output can be partial
    evals = 0
    same = 0
    same_d = 0
    evals_d  = 0

    # finite-difference aproximation step
    diffInt = 1.5e-8
    maxViolation = 1e-2
    _unnamedFunNumber = 1
    _lastDiffVarsID = 0
    _lastFuncVarsID = 0
    _lastOrderVarsID = 0
    criticalPoints = None
    vectorized = False

    _usedIn = 0
    _level = 0
    #_directlyDwasInwolved = False
    _id = 0
    _BroadCastID = 0
    _broadcast_id = 0
    _point_id = 0
    _point_id1 = 0
    _f_key_prev = None
    _f_val_prev = None
    _d_key_prev = None
    _d_val_prev = None
    #_c = 0.0
    __array_priority__ = 15# set it greater than 1 to prevent invoking numpy array __mul__ etc
    
    pWarn = lambda self, msg: pWarn(msg)
    
    def disp(self, msg): 
        print(msg)
    
    def __getattr__(self, attr):
        if attr == '__len__':
            raise AttributeError('using len(oofun) is not possible yet, try using oofun.size instead')
        elif attr == 'isUncycled':
            self._getDep()
            return self.isUncycled
        elif attr != 'size': 
            raise AttributeError('you are trying to obtain incorrect attribute "%s" for FuncDesigner oofun "%s"' %(attr, self.name))
        
        # to prevent creating of several oofuns binded to same oofun.size
        r = oofun(lambda x: asarray(x).size, self, discrete = True, getOrder = lambda *args, **kwargs: 0)
        self.size = r 

        return r

    """                                         Class constructor                                   """

    def __init__(self, fun, input=None, *args, **kwargs):
    #def __init__(self, fun, input=[], *args, **kwargs):
        assert len(args) == 0 #and input is not None
        self.fun = fun
        
        #self._broadcast_id = 0
        self._id = oofun._id
        self.attachedConstraints = set()
        self.args = ()
        oofun._id += 1 # CHECK: it should be int32! Other types cannot be has keys!
        
        if 'name' not in kwargs.keys():
            self.name = 'unnamed_oofun_' + str(oofun._unnamedFunNumber)
            oofun._unnamedFunNumber += 1
        
        for key, item in kwargs.items():
            #print key
            #assert key in self.__allowedFields__ # TODO: make set comparison
            setattr(self, key, item)
            
        if isinstance(input, (tuple, list)): self.input = [(elem if isinstance(elem, oofun) else array(elem, 'float')) for elem in input]
        elif input is not None: self.input = [input]
        else: self.input = [None] # TODO: get rid of None, use input = [] instead

        if input is not None:
            levels = [0]
            for elem in self.input: # if a
                if isinstance(elem, oofun):
                    elem._usedIn += 1
                    levels.append(elem._level)
            self._level = max(levels)+1
            


        

    __hash__ = lambda self: self._id
    
    def named(self, name):
        s = """The function "named" is deprecated and will be removed in future FuncDesigner versions, 
        instead of my_oofun.named('my name')  you should use my_oofun('my name') or my_oofun(name='my name')"""
        self.pWarn(s)
        self.name = name
        return self
        
    def attach(self, *args,  **kwargs):
        if len(kwargs) != 0:
            raise FuncDesignerException('keyword arguments are not implemented for FuncDesigner function "attach"')
        assert len(args) != 0
        Args = args[0] if len(args) == 1 and type(args[0]) in (tuple, list, set) else args
        for arg in Args:
            if not isinstance(arg, BaseFDConstraint):
                raise FuncDesignerException('the FD function "attach" currently expects only constraints')
        self.attachedConstraints.update(Args)
        return self
        
    def removeAttachedConstraints(self):
        self.attachedConstraints = set()    
    __repr__ = lambda self: self.name
    
    def _interval(self, domain, dtype):
        criticalPointsFunc = self.criticalPoints
        if len(self.input) == 1 and criticalPointsFunc is not None:
            arg_infinum, arg_supremum = self.input[0]._interval(domain, dtype)
            if (not isscalar(arg_infinum) and arg_infinum.size > 1) and not self.vectorized:
                raise FuncDesignerException('not implemented for vectorized oovars yet')
            tmp = [arg_infinum, arg_supremum]
            if criticalPointsFunc is not False:
                tmp += criticalPointsFunc(arg_infinum, arg_supremum)
            Tmp = self.fun(vstack(tmp))
#            from numpy import isfinite
#            assert not any(isnan(Tmp))
            return amin(Tmp, 0), amax(Tmp, 0)
        else:
            raise FuncDesignerException('interval calculations are unimplemented for the oofun yet')
    
    def interval(self, domain, dtype = float, *args, **kwargs):
        l, u = self._interval(domain, dtype, *args, **kwargs)
        return Interval(l, u)
        
    # overload "a+b"
    # @checkSizes
    def __add__(self, other):
        if not isinstance(other, (oofun, list, ndarray, tuple)) and not isscalar(other):
            raise FuncDesignerException('operation oofun_add is not implemented for the type ' + str(type(other)))
            
        # TODO: check for correct sizes during f, not only f.d 
    
        def aux_d(x, y):
            Xsize, Ysize = Len(x), Len(y)
            if Xsize == 1:
                return ones(Ysize)
            elif Ysize == 1:
                return Eye(Xsize)
            elif Xsize == Ysize:
                return Eye(Ysize)
            else:
                raise FuncDesignerException('for oofun summation a+b should be size(a)=size(b) or size(a)=1 or size(b)=1')        

        if isinstance(other, oofun):
            r = oofun(lambda x, y: x+y, [self, other], d = (lambda x, y: aux_d(x, y), lambda x, y: aux_d(y, x)))
            r.discrete = self.discrete and other.discrete
            r.getOrder = lambda *args, **kwargs: max((self.getOrder(*args, **kwargs), other.getOrder(*args, **kwargs)))
            
            # TODO: move it outside the func, to prevent recreation each time
            def interval(domain, dtype): 
                domain1, domain2 = self._interval(domain, dtype), other._interval(domain, dtype)
                return domain1[0] + domain2[0], domain1[1] + domain2[1]
            r._interval = interval
        else:
            if isinstance(other,  ooarray): return other + self
            other = array(other, 'float')
#            if other.size == 1:
#                #r = oofun(lambda *ARGS, **KWARGS: None, input = self.input)
#                r = oofun(lambda a: a+other, self)
#                #r._D = lambda *args,  **kwargs: self._D(*args,  **kwargs)
#                r.d = lambda x: aux_d(x, other)
#                #assert len(r._getDep())>0
#                #r._c = self._c + other
#            else:
            r = oofun(lambda a: a+other, self)
            r.d = lambda x: aux_d(x, other)
            r._getFuncCalcEngine = lambda *args,  **kwargs: self._getFuncCalcEngine(*args,  **kwargs) + other
            r.discrete = self.discrete
            r.getOrder = self.getOrder
            r.criticalPoints = False
            #r._interval = lambda domain: (self._interval(domain)[0] + other, self._interval(domain)[1] + other)
            if (other.size == 1 or ('size' in self.__dict__ and self.size == other.size)): 
                r._D = lambda *args,  **kwargs: self._D(*args,  **kwargs) 
        r.vectorized = True
        return r
    
    __radd__ = lambda self, other: self.__add__(other)
    
    # overload "-a"
    def __neg__(self): 
        r = oofun(lambda a: -a, self, d = lambda a: -Eye(Len(a)))
        r._getFuncCalcEngine = lambda *args,  **kwargs: -self._getFuncCalcEngine(*args,  **kwargs)
        r.getOrder = self.getOrder
        r._D = lambda *args, **kwargs: dict([(key, -value) for key, value in self._D(*args, **kwargs).items()])
        r.d = raise_except
        r.criticalPoints = False
        r.vectorized = True
        def _interval(domain, dtype):
            r = self._interval(domain, dtype)
            return (-r[1], -r[0])
        r._interval = _interval
        return r
        
    # overload "a-b"
    __sub__ = lambda self, other: self + (-array(other, 'float')) if type(other) in (list, tuple, ndarray) else self + (-other)
    __rsub__ = lambda self, other: other + (-self)

    # overload "a/b"
    def __div__(self, other):
        if isinstance(other, oofun):
            r = oofun(lambda x, y: x/y, [self, other])
            def aux_dx(x, y):
                x, y, = asfarray(x), asfarray(y) 
                Xsize, Ysize = x.size, y.size
                if Xsize != 1:
                    assert Xsize == Ysize or Ysize == 1, 'incorrect size for oofun devision'
                r = 1.0 / y
                if Xsize != 1:
                    if Ysize == 1: r = atleast_1d(r).tolist() * Xsize
                    r = Diag(r)
                return r                
            def aux_dy(x, y):
                Xsize, Ysize = Len(x), Len(y)
                r = -x / y**2
                if Ysize != 1:
                    assert Xsize == Ysize or Xsize == 1, 'incorrect size for oofun devision'
                    r = Diag(r)
                return r
            r.d = (aux_dx, aux_dy)
            def getOrder(*args, **kwargs):
                order1, order2 = self.getOrder(*args, **kwargs), other.getOrder(*args, **kwargs)
                return order1 if order2 == 0 else inf
            r.getOrder = getOrder
            def interval(domain, dtype):
                lb1, ub1 = self._interval(domain, dtype)
                lb2, ub2 = other._interval(domain, dtype)
                lb2, ub2 = asarray(lb2, dtype), asarray(ub2, dtype)
                #ind1, ind2 = where(lb2==0)[0], where(ub2==0)[0]
                
#                #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
#                th = 1e-150 # TODO: handle it more properly
#                #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
#                
#                lb2[logical_and(lb2>=0, lb2<=th)] = th # then 0.0 / lb2 will be defined correctly and will not yield NaNs
#                ub2[logical_and(ub2<=0, ub2>=-th)] = -th# then 0.0 / ub2 will be defined correctly and will not yield NaNs
                
#                t1, t2, t3, t4 = lb1/lb2, lb1/ub2, ub1/lb2, ub1/ub2
#                ind = lb2 <0 and ub2 >= 0
#                t1[logical_and(ind, lb1] = 
                tmp = vstack((lb1/lb2, lb1/ub2, ub1/lb2, ub1/ub2))
                r1, r2 = nanmin(tmp, 0), nanmax(tmp, 0)
                #ind = logical_or(logical_and(lb1<0, ub1>0), logical_and(lb2<0, ub2>0))
                #ind_z = logical_and(lb2<0, ub2>0)
                ind_z = logical_and(lb2 < 0, ub2 > 0)
                
                ind = logical_or(logical_and(ind_z, lb1<=0), logical_and(lb2 == 0, lb1<0))
                r1[atleast_1d(ind)] = -inf
                
                ind = logical_or(logical_and(ind_z, ub1>=0), logical_and(ub2 == 0, ub1>0))
                r2[atleast_1d(ind)] = inf

                ind = logical_and(lb2==0, lb1>=0)
                r2[atleast_1d(ind)] = inf
                
                ind = logical_and(ub2==0, ub1<=0)
                r1[atleast_1d(ind)] = -inf
                
                return [r1, r2]

            r._interval = interval
        else:
            other = array(other,'float')
            r = oofun(lambda a: a/other, self, discrete = self.discrete)# TODO: involve sparsity if possible!
            r.getOrder = self.getOrder
            r._getFuncCalcEngine = lambda *args,  **kwargs: self._getFuncCalcEngine(*args,  **kwargs) / other
            r.d = lambda x: 1.0/other if (isscalar(x) or x.size == 1) else Diag(ones(x.size)/other)
            r.criticalPoints = False
#            if other.size == 1 or 'size' in self.__dict__ and self.size in (1, other.size):
            if other.size == 1:
                r._D = lambda *args, **kwargs: dict([(key, value/other) for key, value in self._D(*args, **kwargs).items()])
                r.d = raise_except
            
        # r.discrete = self.discrete and (?)
        #r.isCostly = True
        r.vectorized = True
        return r

    def __rdiv__(self, other):
        assert not isinstance(other, oofun)
        other = array(other, 'float') # TODO: sparse matrices handling!
        r = oofun(lambda x: other/x, self, discrete = self.discrete)
        r.d = lambda x: Diag(- other / x**2)
        def interval(domain, dtype):
            arg_infinum, arg_supremum = self._interval(domain, dtype)
            assert other.size == 1, 'this case is unimplemented yet'
            r = vstack((other / arg_supremum, other / arg_infinum))
            r1, r2 = amin(r, 0), amax(r, 0)
            ind = logical_and(arg_infinum < 0,  0 < arg_supremum)
            r1[atleast_1d(ind)] = -inf
            r2[atleast_1d(ind)] = inf
            return [r1, r2]
            
        r._interval = interval
        #r.isCostly = True
        def getOrder(*args, **kwargs):
            order = self.getOrder(*args, **kwargs)
            return 0 if order == 0 else inf
        r.getOrder = getOrder
        r.vectorized = True
        return r

    # overload "a*b"
    def __mul__(self, other):
        if isinstance(other, ooarray):
            return other.__mul__(self)
        def aux_d(x, y):
            Xsize, Ysize = Len(x), Len(y)
            if Xsize == 1:
                return Copy(y)
            elif Ysize == 1:
                r = empty(Xsize)
                r.fill(y)
                return Diag(r)
            elif Xsize == Ysize:
                return Diag(y)
            else:
                raise FuncDesignerException('for oofun multiplication a*b should be size(a)=size(b) or size(a)=1 or size(b)=1')                    
        
        if isinstance(other, oofun):
            r = oofun(lambda x, y: x*y, [self, other])
            r.d = (lambda x, y: aux_d(x, y), lambda x, y: aux_d(y, x))
            r.getOrder = lambda *args, **kwargs: self.getOrder(*args, **kwargs) + other.getOrder(*args, **kwargs)
        else:
            other = array(other, 'float')
            r = oofun(lambda x: x*other, self, discrete = self.discrete)
            r.getOrder = self.getOrder
            r._getFuncCalcEngine = lambda *args,  **kwargs: other * self._getFuncCalcEngine(*args,  **kwargs)
            r.criticalPoints = False

            if other.size == 1:
                r._D = lambda *args, **kwargs: dict([(key, other*value) for key, value in self._D(*args, **kwargs).items()])
                r.d = raise_except
            else:
                r.d = lambda x: aux_d(x, other)
        isOtherOOFun = isinstance(other, oofun)
        def interval(domain, dtype):
            lb1, ub1 = self._interval(domain, dtype)
            
            # works incorrectly
            #lb2, ub2 = other._interval(domain, dtype) if isOtherOOFun else other, other
            
            if isOtherOOFun:
                lb2, ub2 = other._interval(domain, dtype)
            else:
                lb2, ub2 = other, other
            
            if isOtherOOFun:
                t = vstack((lb1 * lb2, ub1 * lb2, \
                            lb1 * ub2, ub1 * ub2))# TODO: improve it
            else:
                t = vstack((lb1 * other, ub1 * other))# TODO: improve it
            t_min, t_max = amin(t, 0), amax(t, 0)
            if isscalar(t_max):
                t_min, t_max = atleast_1d(t_min), atleast_1d(t_max)
            
#            lb1_less_0 = lb1 < 0
#            lb1_eq_0 = lb1 == 0
#            lb1_greater_0 = lb1 > 0
#            
#            ub1_less_0 = ub1 < 0
#            ub1_eq_0 = ub1 == 0
#            ub1_greater_0 = ub1 > 0
            
            ind1_zero_minus = logical_and(lb1<0, ub1>=0)
            ind1_zero_plus = logical_and(lb1<=0, ub1>0)
            
            ind2_zero_minus = logical_and(lb2<0, ub2>=0)
            ind2_zero_plus = logical_and(lb2<=0, ub2>0)
            
            has_plus_inf_1 = logical_or(logical_and(ind1_zero_minus, lb2==-inf), logical_and(ind1_zero_plus, ub2==inf))
            has_plus_inf_2 = logical_or(logical_and(ind2_zero_minus, lb1==-inf), logical_and(ind2_zero_plus, ub1==inf))
            t_max[atleast_1d(logical_or(has_plus_inf_1, has_plus_inf_2))] = inf
            t_max[atleast_1d(logical_or(logical_and(lb1==0, ub2==inf), logical_and(lb2==0, ub1==inf)))] = inf
            t_max[atleast_1d(logical_or(logical_and(lb1==-inf, ub2==0), logical_and(lb2==-inf, ub1==0)))] = 0.0
            
            has_minus_inf_1 = logical_or(logical_and(ind1_zero_plus, lb2==-inf), logical_and(ind1_zero_minus, ub2==inf))
            has_minus_inf_2 = logical_or(logical_and(ind2_zero_plus, lb1==-inf), logical_and(ind2_zero_minus, ub1==inf))
            t_min[atleast_1d(logical_or(has_minus_inf_1, has_minus_inf_2))] = -inf
            t_min[atleast_1d(logical_or(logical_and(lb1==0, ub2==inf), logical_and(lb2==0, ub1==inf)))] = 0.0
            t_min[atleast_1d(logical_or(logical_and(lb1==-inf, ub2==0), logical_and(lb2==-inf, ub1==0)))] = -inf

#            tmp2[atleast_1d(logical_and(logical_and(lb1<0, ub1>=0), lb2==-inf))] = inf
#            tmp2[atleast_1d(logical_and(logical_and(lb1<=0, ub1>0), ub2==inf))] = inf
#            
#            tmp1[atleast_1d(logical_and(logical_and(lb1<0, ub1>=0), ub2==inf))] = -inf
#            tmp1[atleast_1d(logical_and(logical_and(lb1<=0, ub1>0), ub2<0))] = -inf
            
            
#            assert not any(isnan(t_min)) and not any(isnan(t_max))

            
            return t_min, t_max
                
        r._interval = interval
        r.vectorized = True
        #r.isCostly = True
        return r

    __rmul__ = lambda self, other: self.__mul__(other)

    def __pow__(self, other):
        
        d_x = lambda x, y: y * x ** (y - 1) if (isscalar(x) or x.size == 1) else Diag(y * x ** (y - 1))

        d_y = lambda x, y: x ** y * log(x) if (isscalar(y) or y.size == 1) else Diag(x ** y * log(x))
            
        if not isinstance(other, oofun):
            if not isscalar(other): other = array(other)
            f = lambda x: x ** other
            d = lambda x: d_x(x, other)
            input = self
            criticalPoints = ZeroCriticalPoints
        else:
            f = lambda x, y: x ** y
            d = (d_x, d_y)
            input = [self, other]
            def criticalPoints(*args, **kwargs):
                raise FuncDesignerException('interval analysis for pow(oofun,oofun) is unimplemented yet')
        r = oofun(f, input, d = d, criticalPoints=criticalPoints)
        if isinstance(other, oofun) or (not isinstance(other, int) or (type(other) == ndarray and other.flatten()[0] != int)): 
            r.attach((self>0)('pow_domain_%d'%r._id, tol=-1e-7)) # TODO: if "other" is fixed oofun with integer value - omit this
        r.isCostly = True
        r.vectorized = True
        return r

    def __rpow__(self, other):
        assert not isinstance(other, oofun)# if failed - check __pow__implementation
        
        if not isscalar(other) and type(other) != ndarray: other = asfarray(other)
        
        f = lambda x: other ** x
        #d = lambda x: Diag(asarray(other) **x * log(asarray(other)))
        d = lambda x: Diag(other **x * log(other)) 
        r = oofun(f, self, d=d, criticalPoints = False)
        r.isCostly = True
        r.vectorized = True
        return r

    def __xor__(self, other): raise FuncDesignerException('For power of oofuns use a**b, not a^b')
        
    def __rxor__(self, other): raise FuncDesignerException('For power of oofuns use a**b, not a^b')
        
    def __getitem__(self, ind): # overload for oofun[ind]

        if not hasattr(self, '_slicesIndexDict'):
            self._slicesIndexDict = {}
        if ind in self._slicesIndexDict:
            return self._slicesIndexDict[ind]

        if not isinstance(ind, oofun):
            f = lambda x: x[ind]
            def d(x):
                Xsize = Len(x)
                condBigMatrix = Xsize > 100 
                if condBigMatrix and scipyInstalled:
                    r = SparseMatrixConstructor((1, x.shape[0]))
                    r[0, ind] = 1.0
                else: 
                    if not scipyInstalled: self.pWarn(scipyAbsentMsg)
                    r = zeros_like(x)
                    r[ind] = 1
                return r
        else: # NOT IMPLEMENTED PROPERLY YET
            self.pWarn('Slicing oofun by oofun IS NOT IMPLEMENTED PROPERLY YET')
            f = lambda x, _ind: x[_ind]
            def d(x, _ind):
                r = zeros(x.shape)
                r[_ind] = 1
                return r
                
        r = oofun(f, self, d = d, size = 1, getOrder = self.getOrder)
        # TODO: check me!
        # what about a[a.size/2:]?
            
        # TODO: edit me!
#        if self.is_oovar:
#            r.is_oovarSlice = True
        self._slicesIndexDict[ind] = r
        return r
    
    def __getslice__(self, ind1, ind2):# overload for oofun[ind1:ind2]
    
        #raise FuncDesignerException('oofun slicing is not implemented yet')
        
        assert not isinstance(ind1, oofun) and not isinstance(ind2, oofun), 'slicing by oofuns is unimplemented yet'
        f = lambda x: x[ind1:ind2]
        def d(x):
            condBigMatrix = Len(x) > 100 #and (ind2-ind1) > 0.25*x.size
            if condBigMatrix and not scipyInstalled:
                self.pWarn(scipyAbsentMsg)
            
            if condBigMatrix and scipyInstalled:
                r = SP_eye(ind2-ind1)
                if ind1 != 0:
                    m1 = SparseMatrixConstructor((ind2-ind1, ind1))
                    r = Hstack((SparseMatrixConstructor((ind2-ind1, ind1)), r))
                if ind2 != x.size:
                   r = Hstack((r, SparseMatrixConstructor((ind2-ind1, x.size - ind2))))
            else:
                m1 = zeros((ind2-ind1, ind1))
                m2 = eye(ind2-ind1)
                m3 = zeros((ind2-ind1, x.size - ind2))
                r = hstack((m1, m2, m3))
            return r
        r = oofun(f, self, d = d, getOrder = self.getOrder)

        return r
   
    #def __len__(self):
        #return self.size
        #raise FuncDesignerException('using len(obj) (where obj is oovar or oofun) is not possible (at least yet), use obj.size instead')

    def sum(self):
        r = oofun(sum, self, getOrder = self.getOrder)
        def d(x):
            if type(x) == ndarray and x.ndim > 1: raise FuncDesignerException('sum(x) is not implemented yet for arrays with ndim > 1')
            return ones_like(x) 
        r.d = d
        return r
    
    def prod(self):
        # TODO: consider using r.isCostly = True
        r = oofun(prod, self)
        #r.getOrder = lambda *args, **kwargs: self.getOrder(*args, **kwargs)*self.size
        def d(x):
            x = asarray(x) # prod is used rarely, so optimizing it is not important
            if x.ndim > 1: raise FuncDesignerException('prod(x) is not implemented yet for arrays with ndim > 1')
            ind_zero = where(x==0)[0].tolist()
            ind_nonzero = nonzero(x)[0].tolist()
            numOfZeros = len(ind_zero)
            r = prod(x) / x
            
            if numOfZeros >= 2: 
                r[ind_zero] = 0
            elif numOfZeros == 1:
                r[ind_zero] = prod(x[ind_nonzero])

            return r 
        r.d = d
        return r


    """                                     Handling constraints                                  """
    
    # TODO: optimize for lb-ub imposed on oovars
    
    # TODO: fix it for discrete problems like MILP, MINLP
    def __gt__(self, other): # overload for >
        if self.is_oovar and not isinstance(other, oofun):
            r = BoxBoundConstraint(self, lb = other)
        else:
            r = Constraint(self - other, lb=0.0) # do not perform check for other == 0, copy should be returned, not self!
        return r

    # overload for >=
    __ge__ = lambda self, other:  self.__gt__(other)

    # TODO: fix it for discrete problems like MILP
    def __lt__(self, other): # overload for <
        # TODO:
        #(self.is_oovar or self.is_oovarSlice)
        if self.is_oovar and not isinstance(other, oofun):
            r = BoxBoundConstraint(self, ub = other)
        else:
            r = Constraint(self - other, ub = 0.0) # do not perform check for other == 0, copy should be returned, not self!
        return r            

    # overload for <=
    __le__ = lambda self, other: self.__lt__(other)
    
    __eq__ = lambda self, other: self.eq(other)
    
    def eq(self, other):
        if other in (None, (), []): return False
        if self.is_oovar and not isinstance(other, oofun):
            raise FuncDesignerException('Constraints like this: "myOOVar = <some value>" are not implemented yet and are not recommended; for openopt use freeVars / fixedVars instead')
        r = Constraint(self - other, ub = 0.0, lb = 0.0) # do not perform check for other == 0, copy should be returned, not self!
        return r  


    """                                             getInput                                              """
    def _getInput(self, *args, **kwargs):
#        self.inputOOVarTotalLength = 0
        r = []
        for item in self.input:
            tmp = item._getFuncCalcEngine(*args, **kwargs) if isinstance(item, oofun) else item
            r.append(tmp if type(tmp) not in (list, tuple) else asfarray(tmp))
        return tuple(r)

    """                                                getDep                                             """
    def _getDep(self):
        # returns Python set of oovars it depends on
        if hasattr(self, 'dep'):
            return self.dep
        elif self.input is None:
            self.dep = None
        else:
            if type(self.input) not in (list, tuple):
                self.input = [self.input]
            #OLD
#            r = set()
#            for oofunInstance in self.input:
#                if not isinstance(oofunInstance, oofun): continue
#                if oofunInstance.is_oovar:
#                    r.add(oofunInstance)
#                    continue
#                tmp = oofunInstance._getDep()
#                if tmp is None: continue
#                r.update(tmp)
#            self.dep = r    
            # / OLD
            
            # NEW
            r_oovars = []
            r_oofuns = []
            isUncycled = True
            for oofunInstance in self.input:
                if not isinstance(oofunInstance, oofun): continue
                if oofunInstance.is_oovar:
                    r_oovars.append(oofunInstance)
                    continue
                
                tmp = oofunInstance._getDep()
                if not oofunInstance.isUncycled: isUncycled = False
                if tmp is None or len(tmp)==0: continue # TODO: remove None, use [] instead
                r_oofuns.append(tmp)
            r = set(r_oovars)

            # Python 2.5 sel.update fails on empty input
            if len(r_oofuns)!=0: r.update(*r_oofuns)
            if len(r_oovars) + sum([len(elem) for elem in r_oofuns]) != len(r):
                isUncycled = False
            self.isUncycled = isUncycled            
            
            self.dep = r    
            # /NEW
            
        return self.dep


    """                                                getFunc                                             """
    def _getFunc(self, *args, **kwargs):
        Args = args
        if len(args) == 0 and len(kwargs) == 0:
            raise FuncDesignerException('at least one argument is required')
        if len(args) != 0:
            if type(args[0]) != str:
                assert not isinstance(args[0], oofun), "you can't invoke oofun on another one oofun"
                x = args[0]
                if isinstance(x, dict) and not isinstance(x, ooPoint): 
                    x = ooPoint(x)
                    Args = (x,)+args[1:]
                if self.is_oovar:
                    if isinstance(x, dict):
                        tmp = x.get(self, None)
                        if tmp is not None:
                            return float(tmp) if isscalar(tmp) else asfarray(tmp)
                        elif self.name in x:
                            return asfarray(x[self.name])
                        else:
                            s = 'for oovar ' + self.name + \
                            " the point involved doesn't contain neither name nor the oovar instance. Maybe you try to get function value or derivative in a point where value for an oovar is missing"
                            raise FuncDesignerException(s)
                    elif hasattr(x, 'xf'):
                        # TODO: possibility of squeezing
                        return x.xf[self]
                    else:
                        raise FuncDesignerException('Incorrect data type (%s) while obtaining oovar %s value' %(type(x), self.name))
            
            else:
                self.name = args[0]
                return self
        else:
            for fn in ['name', 'size']:
                if fn in kwargs:
                    setattr(self, fn, kwargs[fn])
            return self
                
        return self._getFuncCalcEngine(*Args, **kwargs)


    def _getFuncCalcEngine(self, *args, **kwargs):
        x = args[0]
        
        dep = self._getDep()
        
        CondSamePointByID = True if type(x) == ooPoint and not x.isMultiPoint and self._point_id == x._id else False

        fixedVarsScheduleID = kwargs.get('fixedVarsScheduleID', -1)
        fixedVars = kwargs.get('fixedVars', None)
        Vars = kwargs.get('Vars', None) 
        
        sameVarsScheduleID = fixedVarsScheduleID == self._lastFuncVarsID 
        rebuildFixedCheck = not sameVarsScheduleID
        if fixedVarsScheduleID != -1: self._lastFuncVarsID = fixedVarsScheduleID
        
        if rebuildFixedCheck:
            self._isFixed = (fixedVars is not None and dep.issubset(fixedVars)) or (Vars is not None and dep.isdisjoint(Vars))
            
        cond_same_point = CondSamePointByID or \
        (self._f_val_prev is not None and (self._isFixed or (self.isCostly and  all([array_equal((x if isinstance(x, dict) else x.xf)[elem], self._f_key_prev[elem]) for elem in dep]))))
        
        if cond_same_point:
            self.same += 1
            return self._f_val_prev.copy() # self._f_val_prev is ndarray always 
            
        self.evals += 1
        
        if type(self.args) != tuple:
            self.args = (self.args, )
            
        Input = self._getInput(*args, **kwargs) 
        
        if not isinstance(x, ooPoint) or (not x.isMultiPoint or self.vectorized):
            if self.args != ():
                Input += self.args
            tmp = self.fun(*Input)
        else:
            inputs = zip(*[inp.tolist() for inp in Input])
            tmp = [self.fun(inp if self.args == () else inp + self.args) for inp in inputs]
                
        if isinstance(tmp, (list, tuple)):
            tmp = hstack(tmp)
        
        #if self._c != 0.0: tmp += self._c
        
        #self.outputTotalLength = ([asarray(elem).size for elem in self.fun(*Input)])#self.f_val_prev.size # TODO: omit reassigning
        
        if type(x) == ooPoint: 
            self._point_id = x._id
        
        if (type(x) == ooPoint and not x.isMultiPoint) or self.isCostly or self._isFixed:
            self._f_val_prev = copy(tmp) 
            self._f_key_prev = dict([(elem, copy((x if isinstance(x, dict) else x.xf)[elem])) for elem in dep]) if self.isCostly else None
            r =  copy(self._f_val_prev)
        else:
            r = tmp

        return r


    """                                                getFunc                                             """
    __call__ = lambda self, *args, **kwargs: self._getFunc(*args, **kwargs)


    """                                              derivatives                                           """
    def D(self, x, Vars=None, fixedVars = None, resultKeysType = 'vars', useSparse = False, exactShape = False, fixedVarsScheduleID = -1):
        
        # resultKeysType doesn't matter for the case isinstance(Vars, oovar)
        if Vars is not None and fixedVars is not None:
            raise FuncDesignerException('No more than one argument from "Vars" and "fixedVars" is allowed for the function')
        #assert type(Vars) != ndarray and type(fixedVars) != ndarray
        if not isinstance(x, ooPoint): x = ooPoint(x)
        
        #TODO: remove cloned code
        if Vars is not None:
            if type(Vars) in [list, tuple]:
                Vars = set(Vars)
            elif isinstance(Vars, oofun):
                if not Vars.is_oovar:
                    raise FuncDesignerException('argument Vars is expected as oovar or python list/tuple of oovar instances')
                Vars = set([Vars])
        if fixedVars is not None:
            if type(fixedVars) in [list, tuple]:
                fixedVars = set(fixedVars)
            elif isinstance(fixedVars, oofun):
                if not fixedVars.is_oovar:
                    raise FuncDesignerException('argument fixedVars is expected as oovar or python list/tuple of oovar instances')
                fixedVars = set([fixedVars])
        r = self._D(x, fixedVarsScheduleID, Vars, fixedVars, useSparse = useSparse)
        r = dict([(key, (val if type(val)!=DiagonalType else val.resolve(useSparse))) for key, val in r.items()])
        if isinstance(Vars, oofun):
            if Vars.is_oovar:
                return Vars(r)
            else: 
                # TODO: handle it with input of type list/tuple/etc as well
                raise FuncDesignerException('Cannot perform differentiation by non-oovar input')
        else:
            if resultKeysType == 'names':
                raise FuncDesignerException("""This possibility is out of date, 
                if it is still present somewhere in FuncDesigner doc inform developers""")
            elif resultKeysType == 'vars':
                rr = {}
                tmpDict = Vars if Vars is not None else x
                #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! TODO: remove the cycle!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
                
                for oov, val in x.items():
                    #if not isinstance(oov not in r, bool): print oov not in r
                    if oov not in r or (fixedVars is not None and oov in fixedVars):
                        continue
                    tmp = r[oov]
                    if useSparse == False and hasattr(tmp, 'toarray'): tmp = tmp.toarray()
                    if not exactShape and not isspmatrix(tmp) and not isscalar(tmp):
                        if tmp.size == 1: tmp = asscalar(tmp)
                        elif min(tmp.shape) == 1: tmp = tmp.flatten()
                    rr[oov] = tmp
                return rr
            else:
                raise FuncDesignerException('Incorrect argument resultKeysType, should be "vars" or "names"')
            
            
    def _D(self, x, fixedVarsScheduleID, Vars=None, fixedVars = None, useSparse = 'auto'):
        if self.is_oovar: 
            return {} if (fixedVars is not None and self in fixedVars) or (Vars is not None and self not in Vars) \
            else {self:Eye(asarray(x[self]).size)}
            
        if self.input[0] is None: return {} # fixed oofun. TODO: implement input = [] properly
            
        if self.discrete: 
            return {}
            #raise FuncDesignerException('The oofun or oovar instance has been declared as discrete, no derivative is available')
        
        CondSamePointByID = True if isinstance(x, ooPoint) and self._point_id1 == x._id else False
        sameVarsScheduleID = fixedVarsScheduleID == self._lastDiffVarsID 
        
        dep = self._getDep()
        
        rebuildFixedCheck = not sameVarsScheduleID
        if rebuildFixedCheck:
            self._isFixed = (fixedVars is not None and dep.issubset(fixedVars)) or (Vars is not None and dep.isdisjoint(Vars))
        if self._isFixed: return {}
        ##########################
        
        # TODO: optimize it. Omit it for simple cases.
        #isTransmit = self._usedIn == 1 # Exactly 1! not 0, 2, ,3, 4, etc
        #involveStore = not isTransmit or self._directlyDwasInwolved
        involveStore = self.isCostly

        #cond_same_point = hasattr(self, '_d_key_prev') and sameDerivativeVariables and (CondSamePointByID or (involveStore and         all([array_equal(x[elem], self.d_key_prev[elem]) for elem in dep])))
        
        cond_same_point = sameVarsScheduleID and \
        ((CondSamePointByID and self._d_val_prev is not None) or \
        (involveStore and self._d_key_prev is not None and all([array_equal(x[elem], self._d_key_prev[elem]) for elem in dep])))
        
        if cond_same_point:
            self.same_d += 1
            #return deepcopy(self.d_val_prev)
            return dict([(key, Copy(val)) for key, val in self._d_val_prev.items()])
        else:
            self.evals_d += 1

        if isinstance(x, ooPoint): self._point_id1 = x._id
        if fixedVarsScheduleID != -1: self._lastDiffVarsID = fixedVarsScheduleID

        derivativeSelf = self._getDerivativeSelf(x, fixedVarsScheduleID, Vars, fixedVars)

        r = Derivative()
        ac = -1
        for i, inp in enumerate(self.input):
            if not isinstance(inp, oofun): continue
            if inp.discrete: continue

            if inp.is_oovar: 
                if (Vars is not None and inp not in Vars) or (fixedVars is not None and inp in fixedVars):
                    continue                
                ac += 1
                tmp = derivativeSelf[ac]

                if inp in r:
                    if isscalar(tmp) or (type(r[inp]) == type(tmp) == ndarray and prod(tmp.shape) <= prod(r[inp].shape)): # some sparse matrices has no += implemented 
                        r[inp] += tmp
                    else:
                        r[inp] = r[inp] + tmp
                else:
                    r[inp] = tmp
            else:
                ac += 1
                
                elem_d = inp._D(x, fixedVarsScheduleID, Vars=Vars, fixedVars=fixedVars, useSparse = useSparse) 
                
                t1 = derivativeSelf[ac]
                
                for key, val in elem_d.items():
                    if type(t1) == DiagonalType or type(val) == DiagonalType:
                        if isspmatrix(t1):
                            rr = t1._mul_sparse_matrix(val.resolve(True))
                        else:
                            rr = t1 *  val
#                        if isscalar(t1) or isscalar(val) or (type(t1) == DiagonalType and type(val) == DiagonalType):
#                            rr = t1 * val
#                        else: # ndarray or sparse matrix is present
                            
                    elif isscalar(val) or isscalar(t1) or prod(t1.shape)==1 or prod(val.shape)==1:
                        #rr = t1 * val
                        rr = (t1 if isscalar(t1) or prod(t1.shape)>1 else asscalar(t1) if type(t1)==ndarray else t1[0, 0]) \
                        * (val if isscalar(val) or prod(val.shape)>1 else asscalar(val) if type(val)==ndarray else val[0, 0])
                    else:
                        if val.ndim < 2: val = atleast_2d(val)
                        if useSparse is False:
                            t2 = val
                        else:
                            t1, t2 = self._considerSparse(t1, val)
                        
                        if not type(t1) == type(t2) ==  ndarray:
                            # CHECKME: is it trigger somewhere?
                            if not scipyInstalled:
                                self.pWarn(scipyAbsentMsg)
                                rr = dot(t1, t2)
                            else:
                                t1 = t1 if isspmatrix_csc(t1) else t1.tocsc() if isspmatrix(t1)  else scipy.sparse.csc_matrix(t1)
                                t2 = t2 if isspmatrix_csr(t2) else t2.tocsr() if isspmatrix(t2)  else scipy.sparse.csr_matrix(t2)
                                if t2.shape[0] != t1.shape[1]:
                                    if t2.shape[1] == t1.shape[1]:
                                        t2 = t2.T
                                    else:
                                        raise FuncDesignerException('incorrect shape in FuncDesigner function _D(), inform developers about the bug')
                                rr = t1._mul_sparse_matrix(t2)
                                if useSparse is False:
                                    rr = rr.toarray() 
                        else:
                            rr = dot(t1, t2)
                    #assert rr.ndim>1
                    
                    Val = r.get(key, None)
                    if Val is not None:
                        if isinstance(Val, ndarray) and hasattr(rr, 'toarray'): # i.e. rr is sparse matrix
                            rr = rr.toarray() # I guess r[key] will hardly be all-zeros
                        elif hasattr(Val, 'toarray') and isinstance(rr, ndarray): # i.e. Val is sparse matrix
                            Val = Val.toarray()
                        if type(rr) == type(Val) == ndarray and rr.size == Val.size: 
                            Val += rr
                        else: 
                            r[key] = Val + rr
                    else:
                        r[key] = rr
        
        self._d_val_prev = dict([(key, Copy(value)) for key, value in r.items()])
        self._d_key_prev = dict([(elem, Copy(x[elem])) for elem in dep]) if involveStore else None
        return r

    # TODO: handle 2**15 & 0.25 as parameters
    def _considerSparse(self, t1, t2):  
        if prod(t1.shape) * prod(t2.shape) > 2**15 and   (isinstance(t1, ndarray) and t1.nonzero()[0].size < 0.25*t1.size) or \
        (isinstance(t2, ndarray) and t2.nonzero()[0].size < 0.25*t2.size):
            if scipy is None: 
                self.pWarn(scipyAbsentMsg)
                return t1,  t2
            if not isinstance(t1, scipy.sparse.csc_matrix): 
                t1 = scipy.sparse.csc_matrix(t1)
            if t1.shape[1] != t2.shape[0]: # can be from flattered t1
                assert t1.shape[0] == t2.shape[0], 'bug in FuncDesigner Kernel, inform developers'
                t1 = t1.T
            if not isinstance(t2, scipy.sparse.csr_matrix): 
                t2 = scipy.sparse.csr_matrix(t2)
        return t1,  t2

    def _getDerivativeSelf(self, x, fixedVarsScheduleID, Vars,  fixedVars):
        Input = self._getInput(x, fixedVarsScheduleID=fixedVarsScheduleID, Vars=Vars,  fixedVars=fixedVars)
        expectedTotalInputLength = sum([Len(elem) for elem in Input])
        
#        if hasattr(self, 'size') and isscalar(self.size): nOutput = self.size
#        else: nOutput = self(x).size 

        hasUserSuppliedDerivative = self.d is not None
        if hasUserSuppliedDerivative:
            derivativeSelf = []
            if type(self.d) == tuple:
                if len(self.d) != len(self.input):
                   raise FuncDesignerException('oofun error: num(derivatives) not equal to neither 1 nor num(inputs)')
                   
                indForDiff = []
                for i, deriv in enumerate(self.d):
                    inp = self.input[i]
                    if not isinstance(inp, oofun) or inp.discrete: 
                        #if deriv is not None: 
                            #raise FuncDesignerException('For an oofun with some input oofuns declared as discrete you have to set oofun.d[i] = None')
                        continue
                    
                    #!!!!!!!!! TODO: handle fixed cases properly!!!!!!!!!!!!
                    #if hasattr(inp, 'fixed') and inp.fixed: continue
                    if inp.is_oovar and ((Vars is not None and inp not in Vars) or (fixedVars is not None and inp in fixedVars)):
                        continue
                        
                    if deriv is None:
                        if not DerApproximatorIsInstalled:
                            raise FuncDesignerException('To perform gradients check you should have DerApproximator installed, see http://openopt.org/DerApproximator')
                        derivativeSelf.append(get_d1(self.fun, Input, diffInt=self.diffInt, stencil = self.stencil, \
                                                     args=self.args, varForDifferentiation = i, pointVal = self._getFuncCalcEngine(x), exactShape = True))
                    else:
                        # !!!!!!!!!!!!!! TODO: add check for user-supplied derivative shape
                        tmp = deriv(*Input)
                        if not isscalar(tmp) and type(tmp) in (ndarray, tuple, list) and type(tmp) != DiagonalType: # i.e. not a scipy.sparse matrix
                            tmp = atleast_2d(tmp)
                            
                            ########################################

                            _tmp = Input[i]
                            Tmp = 1 if isscalar(_tmp) or prod(_tmp.shape) == 1 else len(Input[i])
                            if tmp.shape[1] != Tmp: 
                                # TODO: add debug msg
#                                print('incorrect shape in FD AD _getDerivativeSelf')
#                                print tmp.shape[0], nOutput, tmp
                                if tmp.shape[0] != Tmp: raise FuncDesignerException('error in getDerivativeSelf()')
                                tmp = tmp.T
                                    
                            ########################################
                            
                        derivativeSelf.append(tmp)
            else:
                tmp = self.d(*Input)
                if not isscalar(tmp) and type(tmp) in (ndarray, tuple, list): # i.e. not a scipy.sparse matrix
                    tmp = atleast_2d(tmp)
                    
                    if tmp.shape[1] != expectedTotalInputLength: 
                        # TODO: add debug msg
                        if tmp.shape[0] != expectedTotalInputLength: raise FuncDesignerException('error in getDerivativeSelf()')
                        tmp = tmp.T
                        
                ac = 0
                if isinstance(tmp, ndarray) and hasattr(tmp, 'toarray'): tmp = tmp.A # is dense matrix
                
                #if not isinstance(tmp, ndarray) and not isscalar(tmp) and type(tmp) != DiagonalType:
                if len(Input) == 1:
                    derivativeSelf = [tmp]
                else:
                    for i, inp in enumerate(Input):
                        t = self.input[i]
                        if t.discrete or (t.is_oovar and ((Vars is not None and t not in Vars) or (fixedVars is not None and t in fixedVars))):
                            ac += inp.size
                            continue                                    
                        if isinstance(tmp, ndarray):
                            TMP = tmp[:, ac:ac+Len(inp)]
                        elif isscalar(tmp):
                            TMP = tmp
                        elif type(tmp) == DiagonalType: 
                            # TODO: mb rework it
                            if inp.size > 150 and tmp.size > 150:
                                tmp = tmp.resolve(True).tocsc()
                            else: tmp =  tmp.resolve(False) 
                            TMP = tmp[:, ac:ac+inp.size]
                        else: # scipy.sparse matrix
                            TMP = tmp.tocsc()[:, ac:ac+inp.size]
                        ac += Len(inp)
                        derivativeSelf.append(TMP)
                    
            # TODO: is it required?
#                if not hasattr(self, 'outputTotalLength'): self(x)
#                
#                if derivativeSelf.shape != (self.outputTotalLength, self.inputTotalLength):
#                    s = 'incorrect shape for user-supplied derivative of oofun '+self.name+': '
#                    s += '(%d, %d) expected, (%d, %d) obtained' % (self.outputTotalLength, self.inputTotalLength,  derivativeSelf.shape[0], derivativeSelf.shape[1])
#                    raise FuncDesignerException(s)
        else:
            if Vars is not None or fixedVars is not None: raise FuncDesignerException("sorry, custom oofun derivatives don't work with Vars/fixedVars arguments yet")
            if not DerApproximatorIsInstalled:
                raise FuncDesignerException('To perform this operation you should have DerApproximator installed, see http://openopt.org/DerApproximator')
                
            derivativeSelf = get_d1(self.fun, Input, diffInt=self.diffInt, stencil = self.stencil, args=self.args, pointVal = self._getFuncCalcEngine(x), exactShape = True)
            if type(derivativeSelf) == tuple:
                derivativeSelf = list(derivativeSelf)
            elif type(derivativeSelf) != list:
                derivativeSelf = [derivativeSelf]
        
        #assert all([elem.ndim > 1 for elem in derivativeSelf])
       # assert len(derivativeSelf[0])!=16
        #assert (type(derivativeSelf[0]) in (int, float)) or derivativeSelf[0][0]>480.00006752 or derivativeSelf[0][0]<480.00006750
        return derivativeSelf

    def D2(self, x):
        raise FuncDesignerException('2nd derivatives for obj-funcs are not implemented yet')

    def check_d1(self, point):
        if self.d is None:
            self.disp('Error: no user-provided derivative(s) for oofun ' + self.name + ' are attached')
            return # TODO: return non-void result
        separator = 75 * '*'
        self.disp(separator)
        assert type(self.d) != list
        val = self(point)
        input = self._getInput(point)
        ds= self._getDerivativeSelf(point, fixedVarsScheduleID = -1, Vars=None,  fixedVars=None)
        self.disp(self.name + ': checking user-supplied gradient')
        self.disp('according to:')
        self.disp('    diffInt = ' + str(self.diffInt)) # TODO: ADD other parameters: allowed epsilon, maxDiffLines etc
        self.disp('    |1 - info_user/info_numerical| < maxViolation = '+ str(self.maxViolation))        
        j = -1
        for i in xrange(len(self.input)):#var in Vars:
            var = self.input[i]
            if len(self.input) > 1: self.disp('by input variable number ' + str(i) + ':')
            if isinstance(self.d, tuple) and self.d[i] is None:
                self.disp('user-provided derivative for input number ' + str(i) + ' is absent, skipping the one;')
                self.disp(separator)
                continue
            if not isinstance(self.input[i], oofun):
                self.disp('input number ' + str(i) + ' is not oofun instance, skipping the one;')
                self.disp(separator)
                continue
            j += 1
            check_d1(lambda *args: self.fun(*args), ds[j], input, \
                 func_name=self.name, diffInt=self.diffInt, pointVal = val, args=self.args, \
                 stencil = max((3, self.stencil)), maxViolation=self.maxViolation, varForCheck = i)

    def getOrder(self, Vars=None, fixedVars=None, fixedVarsScheduleID=-1):
        
        # TODO: improve it wrt fixedVarsScheduleID
        
        # returns polinomial order of the oofun
        if isinstance(Vars, oofun): Vars = set([Vars])
        elif Vars is not None and type(Vars) != set: Vars = set(Vars)
        
        if isinstance(fixedVars, oofun): fixedVars = set([fixedVars])
        elif fixedVars is not None and type(fixedVars) != set: fixedVars = set(fixedVars)
        
        sameVarsScheduleID = fixedVarsScheduleID == self._lastOrderVarsID 
        rebuildFixedCheck = not sameVarsScheduleID
        if fixedVarsScheduleID != -1: self._lastOrderVarsID = fixedVarsScheduleID
        
        if rebuildFixedCheck:
            # ajust new value of self._order wrt new free/fixed vars schedule
            if self.discrete: self._order = 0
       
            if self.is_oovar:
                if (fixedVars is not None and self in fixedVars) or (Vars is not None and self not in Vars):
                    self._order = 0
                else:
                    self._order = 1
            else:
                orders = [(inp.getOrder(Vars, fixedVars) if isinstance(inp, oofun) else 0) for inp in self.input]
                self._order = inf if any(asarray(orders) != 0) else 0

        return self._order
    
    # TODO: should broadcast return non-void result?
    def _broadcast(self, func, *args, **kwargs):
        if self._broadcast_id == oofun._BroadCastID: 
            return # already done for this one
            
        self._broadcast_id = oofun._BroadCastID
        
        # TODO: possibility of reverse order?
        if self.input is not None:
            for inp in self.input: 
                if not isinstance(inp, oofun): continue
                inp._broadcast(func, *args, **kwargs)
        for c in self.attachedConstraints:
            c._broadcast(func, *args, **kwargs)
        func(self)
        
#    def isUncycled(self):
#        # TODO: speedup the function via omitting same oofuns
#        # TODO: handle fixed variables
#        deps = []
#        oofuns = []
#        dep_num = []
#        for elem in self._getDep():
#            if isinstance(elem, oofun):
#                if elem.is_oovar:
#                    deps.append(elem)
#                    dep_num.append(1)
#                else:
#                    tmp = elem._getDep()
#                    dep_num.append(len(tmp))
#                    if tmp is not None:
#                        deps.append(tmp)
#                    oofuns.append(elem)
#                    
#        if any([not elem.isUncycled() for elem in oofuns]):
#            return False
#        r1 = set()
#        r1.update(deps)
#        return True if len(r1) == sum(dep_num) else False
        
    def uncertainty(self, point, deviations, actionOnAbsentDeviations='warning'):
        ''' 
        result = oofun.uncertainty(point, deviations, actionOnAbsentDeviations='warning')
        point and deviations should be Python dicts of pairs (oovar, value_for_oovar)
        actionOnAbsentDeviations = 
        'error' (raise FuncDesigner exception) | 
        'skip' (treat as fixed number with zero deviation) |
        'warning' (print warning, treat as fixed number) 
        
        Sparse large-scale examples haven't been tested,
        we could implement and test it properly on demand
        '''
        dep = self._getDep()
        dev_keys = set(deviations.keys())
        set_diff = dep.difference(dev_keys)
        nAbsent = len(set_diff)
        if actionOnAbsentDeviations != 'skip':
            if len(set_diff) != 0:
                if actionOnAbsentDeviations == 'warning':
                    pWarn('''
                    dict of deviations miss %d variables (oovars): %s;
                    they will be treated as fixed numbers with zero deviations
                    ''' % (nAbsent, list(set_diff)))
                else:
                    raise FuncDesignerException('dict of deviations miss %d variable(s) (oovars): %s' % (nAbsent, list(set_diff)))
        
        d = self.D(point, exactShape=True) if nAbsent == 0 else self.D(point, fixedVars = set_diff, exactShape=True)
        tmp = [dot(val, (deviations[key] if isscalar(deviations[key]) else asarray(deviations[key]).reshape(-1, 1)))**2 for key, val in d.items()]
        tmp = [asscalar(elem) if isinstance(elem, ndarray) and elem.size == 1 else elem for elem in tmp]
        r = atleast_2d(hstack(tmp)).sum(1)
        return r ** 0.5
        
   
        """                                             End of class oofun                                             """

# TODO: make it work for ooSystem as well
def broadcast(func, oofuncs, *args, **kwargs):
    oofun._BroadCastID += 1
    for oof in oofuncs:
        if oof is not None: 
            oof._broadcast(func, *args, **kwargs)

def _getAllAttachedConstraints(oofuns):
    from FuncDesigner import broadcast
    r = set()
    def F(oof):
        #print len(oof.attachedConstraints)
        r.update(oof.attachedConstraints)
    broadcast(F, oofuns)
    return r

class BooleanOOFun(oofun):
    _unnamedBooleanOOFunNumber = 0
    discrete = True
    # an oofun that returns True/False
    def __init__(self, oofun_Involved, *args, **kwargs):
        oofun.__init__(self, oofun_Involved._getFuncCalcEngine, (oofun_Involved.input if not oofun_Involved.is_oovar else oofun_Involved), *args, **kwargs)
        #self.input = oofun_Involved.input
        BooleanOOFun._unnamedBooleanOOFunNumber += 1
        self.name = 'unnamed_boolean_oofun_' + str(BooleanOOFun._unnamedBooleanOOFunNumber)
        
    def size(self, *args, **kwargs): raise FuncDesignerException('currently BooleanOOFun.size() is disabled')
    def D(self, *args, **kwargs): raise FuncDesignerException('currently BooleanOOFun.D() is disabled')
    def _D(self, *args, **kwargs): raise FuncDesignerException('currently BooleanOOFun._D() is disabled')

class BaseFDConstraint(BooleanOOFun):
    isConstraint = True
    tol = 0.0 
    expected_kwargs = set(['tol', 'name'])
    #def __getitem__(self, point):

    def __call__(self, *args,  **kwargs):
        expected_kwargs = self.expected_kwargs
        if not set(kwargs.keys()).issubset(expected_kwargs):
            raise FuncDesignerException('Unexpected kwargs: should be in '+str(expected_kwargs)+' got: '+str(kwargs.keys()))
            
        for elem in expected_kwargs:
            if elem in kwargs:
                setattr(self, elem, kwargs[elem])
        
        if len(args) > 1: raise FuncDesignerException('No more than single argument is expected')
        
        if len(args) == 0:
           if len(kwargs) == 0: raise FuncDesignerException('You should provide at least one argument')
           return self
           
        if isinstance(args[0], str):
            self.name = args[0]
            return self
        elif hasattr(args[0], 'xf'):
            return self(args[0].xf)
            
        return self._getFuncCalcEngine(*args,  **kwargs)
        
    def _getFuncCalcEngine(self, *args,  **kwargs):
    
        if isinstance(args[0], dict): # is FD Point
            val = self.oofun(args[0])
            if any(isnan(val)):
                return False
            Tol = max((0.0, self.tol))
            if any(atleast_1d(self.lb-val)>Tol):
                return False
            elif any(atleast_1d(val-self.ub)>Tol):
                return False
            return True
        else:
            raise FuncDesignerException('unexpected type: %s' % type(args[0]))

    def __init__(self, oofun_Involved, *args, **kwargs):
        BooleanOOFun.__init__(self, oofun_Involved, *args, **kwargs)
        #oofun.__init__(self, lambda x: oofun_Involved(x), input = oofun_Involved)
        if len(args) != 0:
            raise FuncDesignerException('No args are allowed for FuncDesigner constraint constructor, only some kwargs')
            
        # TODO: replace self.oofun by self.engine
        self.oofun = oofun_Involved
        

class SmoothFDConstraint(BaseFDConstraint):
        
    __getitem__ = lambda self, point: self.__call__(point)
        
    def __init__(self, *args, **kwargs):
        BaseFDConstraint.__init__(self, *args, **kwargs)
        self.lb, self.ub = -inf, inf
        for key in kwargs.keys():
            if key in ['lb', 'ub']:
                setattr(self, key, asfarray(kwargs[key]))
            else:
                raise FuncDesignerException('Unexpected key in FuncDesigner constraint constructor kwargs')
    

class Constraint(SmoothFDConstraint):
    def __init__(self, *args, **kwargs):
        SmoothFDConstraint.__init__(self, *args, **kwargs)
        
        
class BoxBoundConstraint(SmoothFDConstraint):
    def __init__(self, *args, **kwargs):
        SmoothFDConstraint.__init__(self, *args, **kwargs)
        
class Derivative(dict):
    def __init__(self):
        pass


def ooFun(*args, **kwargs):
    r = oofun(*args, **kwargs)
    r.isCostly = True
    return r

def atleast_oofun(arg):
    if isinstance(arg, oofun):
        return arg
    elif hasattr(arg, 'copy'):
        tmp = arg.copy()
        return oofun(lambda *args, **kwargs: tmp, input = None, getOrder = lambda *args,  **kwargs: 0, discrete=True)#, isConstraint = True)
    elif isscalar(arg):
        tmp = array(arg, 'float')
        return oofun(lambda *args, **kwargs: tmp, input = None, getOrder = lambda *args,  **kwargs: 0, discrete=True)#, isConstraint = True)
    else:
        #return oofun(lambda *args, **kwargs: arg(*args,  **kwargs), input=None, discrete=True)
        raise FuncDesignerException('incorrect type for the function _atleast_oofun')


class ooarray(ndarray):
    
    __array_priority__ = 25 # !!! it should exceed oofun.__array_priority__ !!!
    
    def __new__(self, *args, **kwargs):
        assert len(kwargs) == 0
        obj = asarray(args[0] if len(args) == 1 else args).view(self)
        #if obj.ndim != 1: raise FuncDesignerException('only 1-d ooarrays are implemented now')
        #if obj.dtype != object:obj = np.asfarray(obj) #TODO: FIXME !
        return obj

    def __call__(self, *args, **kwargs):
        #if self.dtype != object: return asfarray(self)
        Args = ((args[0], )+ (args[1:])) if len(args) != 0 and type(args[0]) == dict else args
#        tmp = []
#        for i in range(self.size):
#            Tmp = self[i](*args, **kwargs) 
#            if asscalar(
        tmp = [asscalar(asarray(self[i](*args, **kwargs)) if isinstance(self[i], oofun) else self[i]) for i in range(self.size)]
        return array(tmp, dtype=float).flatten()

    def __mul__(self, other):
        if self.size == 1:
            return ooarray(asscalar(self)*other)
        elif isscalar(other):
            return ooarray(self.view(ndarray)*other if self.dtype != object else [self[i]*other for i in range(self.size)])
        elif isinstance(other, oofun):
            hasSize = 'size' in dir(other)
            if not hasSize: raise FuncDesignerException('to perform the operation oofun size should be known')
            if other.size == 1:
                if self.dtype == object:
                    return ooarray([self[i]*other for i in range(self.size)])
                else:
                    return ooarray(self*other)
            else: # other.size > 1
                # and self.size != 1
                return ooarray([self[i]*other[i] for i in range(self.size)])
        elif isinstance(other, ndarray):
            return ooarray(self*asscalar(other) if other.size == 1 else [self[i]*other[i] for i in range(other.size)])
        else:
            raise SpaceFuncsException('bug in multiplication')

    def __div__(self, other):
        if self.size == 1:
            return asscalar(self)/other
        elif isscalar(other) or isinstance(other, ndarray) and other.size == 1:
            return self * (1.0/other)
        elif isinstance(other, oofun):
            if self.dtype != object:
                return self.view(ndarray) / other
            else:
                return ooarray([self[i] / other for i in range(self.size)])
        elif isinstance(other, ooarray):
            if self.dtype != object:
                return self.view(ndarray) / other.view(ndarray)
            else:
                return ooarray([self[i] / other[i] for i in range(self.size)])
        else:
            raise FuncDesignerException('unimplemented yet')

    def __add__(self, other):
        if isinstance(other, list):
            other = ooarray(other)
        if isscalar(other) or isinstance(other, ndarray) and other.size == 1:
            return ooarray(self.view(ndarray) + other)
        elif isinstance(other, oofun):
            if self.dtype != object:
                return self.view(ndarray) + other
            else:
                return ooarray([self[i] + other for i in range(self.size)])
        elif isinstance(other, ndarray):
            if self.dtype != object:
                return self.view(ndarray) + other.view(ndarray)
            else:
                return ooarray([self[i] + other[i] for i in range(self.size)])
        else:
            raise FuncDesignerException('unimplemented yet')

    # TODO: check why it doesn't work with oofuns
    def __radd__(self, other):
        return self + other
    
    def __pow__(self, other):
        if self.dtype == object:
            return ooarray([elem**other for elem in self.tolist()])
        else:
            return self.view(ndarray)**other
    
    def __eq__(self, other):
        r = self - other
        if r.dtype != object: return all(r)
        if r.size == 1: return asscalar(r)==0
        
        # TODO: rework it
        return [Constraint(elem) for elem in r.tolist()]
        #else: raise FuncDesignerException('unimplemented yet')
        
        
# TODO: implement it!
# TODO: check __mul__ and __div__ for oofun with size > 1

#    def __add__(self, other):
#        if isscalar(other) or isinstance(other, ndarray) and other.size == 1:
#            return self + other
#        elif  isinstance(other, oofun):
#            
