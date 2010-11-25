from numpy import diag, array, sqrt,  eye, ones, inf, any, copy, zeros, dot, where, all, tile, sum, nan, isfinite, float64, isnan, log10, \
max, sign, array_equal, nonzero, ix_, arctan, pi, logical_not, logical_and, atleast_2d, matrix, delete, empty, ndarray, \
logical_and, logical_not
from numpy.linalg import norm, solve, LinAlgError

from openopt.kernel.baseSolver import *
from openopt.kernel.Point import Point
from openopt.kernel.setDefaultIterFuncs import *
from UkrOptMisc import getBestPointAfterTurn
from PolytopProjection import PolytopProjection

class gsubg(baseSolver):
    __name__ = 'gsubg'
    __license__ = "BSD"
    __authors__ = "Dmitrey"
    __alg__ = "Nikolay G. Zhurbenko generalized epsilon-subgradient"
    #__optionalDataThatCanBeHandled__ = ['A', 'Aeq', 'b', 'beq', 'lb', 'ub', 'c', 'h']
    iterfcnConnected = True
    _canHandleScipySparse = True

    #gsubg default parameters
    h0 = 1.0
    hmult = 0.5
    T = float64
    
    showLS = False
    show_hs = False
    showRes = False
    show_nnan = False
    doBackwardSearch = True
    new_bs = True
    approach = 'all active'
    zhurb = 100
    sigma = 1e-3
    dual = True
    ls_direction = 'simple'
    qpsolver = 'cvxopt_qp'
    ns = 15

    def __init__(self): pass
    def __solver__(self, p):
        assert self.approach == 'all active'
        
#        LB, UB = p.lb, p.ub
#        fin_lb = isfinite(LB)
#        fin_ub = isfinite(UB)
#        ind_lb = where(fin_lb)[0]
#        ind_ub = where(fin_ub)[0]
#        ind_only_lb = where(logical_and(fin_lb, logical_not(fin_ub)))[0]
#        ind_only_ub = where(logical_and(fin_ub, logical_not(fin_lb)))[0]
#        ind_bb = where(logical_and(fin_ub, fin_lb))[0]
#        lb_val = LB[ind_only_lb]
#        ub_val = UB[ind_only_ub]
#        dist_lb_ub = UB[ind_bb] - LB[ind_bb]
#        double_dist_lb_ub = 2 * dist_lb_ub
#        ub_bb = UB[ind_bb]
#        doubled_ub_bb = 2 * ub_bb
#        def Point(x):
#            z = x.copy()
#            z[ind_only_lb] = abs(x[ind_only_lb]-lb_val) + lb_val
#            z[ind_only_ub] = ub_val - abs(x[ind_only_ub]-ub_val) 
#            
#            ratio = x[ind_bb] / double_dist_lb_ub
#            z1 = x[ind_bb] - array(ratio, int) * double_dist_lb_ub
#            ind = where(z1>ub_bb)[0]
#            z1[ind] = doubled_ub_bb - z1[ind]
#            z[ind_bb] = z1
#            #raise 0
#            return p.point(z)
        Point = lambda x: p.point(x)
        
        h0 = self.h0

        T = self.T
        # alternatively instead of alp=self.alp etc you can use directly self.alp etc

        n = p.n
        x0 = p.x0
        
        if p.nbeq == 0 or any(abs(p._get_AeqX_eq_Beq_residuals(x0))>p.contol): # TODO: add "or Aeqconstraints(x0) out of contol"
            x0[x0<p.lb] = p.lb[x0<p.lb]
            x0[x0>p.ub] = p.ub[x0>p.ub]
        
        hs = asarray(h0, T)
        ls_arr = []

        """                         Nikolay G. Zhurbenko generalized epsilon-subgradient engine                           """
        bestPoint = Point(asarray(copy(x0), T))
        bestFeasiblePoint = None if not bestPoint.isFeas(True) else bestPoint
        prevIter_best_ls_point = bestPoint
        best_ls_point = bestPoint
        iterStartPoint = bestPoint
        prevIter_bestPointAfterTurn = bestPoint
        bestPointBeforeTurn = None
        g = bestPoint._getDirection(self.approach)
        g1 = iterStartPoint._getDirection(self.approach, currBestFeasPoint = bestFeasiblePoint)
        if not any(g) and all(isfinite(g)):
            # TODO: create ENUMs
            p.istop = 14 if bestPoint.isFeas(False) else -14
            p.msg = 'move direction has all-zero coords'
            return

        HS = []
        LS = []
        
        # TODO: add possibility to handle f_opt if known instead of Ftol
        #Ftol = 1.0
        if p.Ftol is None:
            p.warn('The solver requres user-supplied Ftol (objective function tolerance); 15*ftol will be used')
            p.Ftol = 15 * p.ftol
        Ftol_start = p.Ftol/2.0
        Ftol = Ftol_start
        
        subGradientNorms, points, values, isConstraint, epsilons, inactive, normedSubGradients, normed_values = [], [], [], [], [], [], [], []
        StoredInfo = [subGradientNorms, points, values, isConstraint, epsilons, inactive, normedSubGradients, normed_values]
        nMaxVec = self.zhurb
        nVec = 0
        ns = 0
        #ScalarProducts = empty((10, 10))
        maxQPshoutouts = 15
        
        
        """                           gsubg main cycle                                    """

        for itn in xrange(1500000):
            # TODO: change inactive data removing 
            # TODO: change inner cycle condition
            # TODO: improve 2 points obtained from backward line search
            koeffs = None
            
            while ns < self.ns:
                
                ns += 1
                nAddedVectors = 0
                projection = None
                F0 = asscalar(bestFeasiblePoint.f() - Ftol_start) if bestFeasiblePoint is not None else nan
                
                #iterStartPoint = prevIter_best_ls_point
                if bestPointBeforeTurn is None:
                    schedule = [bestPoint]
                    #x = iterStartPoint.x
                else:
                    sh = [point1, point2]
                    #sh = [iterStartPoint, bestPointBeforeTurn, bestPointAfterTurn]
                    sh.sort(cmp = lambda point1, point2: -1+2*int(point1.betterThan(point2, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint)))
                    iterStartPoint = sh[-1]
                    schedule = [point for point in sh if id(point.x) != id(points[-1])]
                    #x = iterStartPoint.x.copy()
                    #x = 0.5*(point1.x+point2.x) 
                #print 'len(schedule):', len(schedule)
                
                # DEBUG
#                schedule = [Point([0]), Point([1])]
#                iterStartPoint = p.point([0])
                # DEBUG END
                
                x = iterStartPoint.x.copy()
                #print 'itn:', itn, 'ns:', ns, 'x:', x, 'hs:', hs
#                if itn != 0:
#                    Xdist = norm(prevIter_best_ls_point.x-bestPointAfterTurn.x)
#                    if hs < 0.25*Xdist :
#                        hs = 0.25*Xdist
                
                
                iterInitialDataSize = len(values)
                for point in schedule:
                    if isfinite(point.f()) and bestFeasiblePoint is not None:
                        tmp = point.df()
                        if not isinstance(tmp, ndarray) or isinstance(tmp, matrix):
                            tmp = tmp.A
                        tmp = tmp.flatten()
                        n_tmp = norm(tmp)
                        if n_tmp < p.gtol:
                            p._df = n_tmp # TODO: change it 
                            p.iterfcn(point)
                            return
                        nVec += 1
                        normedSubGradients.append(tmp/n_tmp)
                        subGradientNorms.append(n_tmp)
                        val = point.f()
                        values.append(asscalar(val))
                        normed_values.append(asscalar(val/n_tmp))
                        epsilons.append(asscalar((val + dot(point.x, tmp))/n_tmp))
                        isConstraint.append(False)
                        points.append(point.x)
                        inactive.append(0)
                        nAddedVectors += 1
                    if not point.isFeas(True):
                        # TODO: use old-style w/o the arg "currBestFeasPoint = bestFeasiblePoint"
                        #tmp = point._getDirection(self.approach, currBestFeasPoint = bestFeasiblePoint)
                        nVec += 1
                        tmp = point._getDirection(self.approach)
                        if not isinstance(tmp, ndarray) or isinstance(tmp, matrix):
                            tmp = tmp.A.flatten()
                        n_tmp = norm(tmp)
                        normedSubGradients.append(tmp/n_tmp)
                        subGradientNorms.append(n_tmp)
                        val = point.mr_alt()
                        values.append(val)
                        normed_values.append(asscalar(val/n_tmp))
                        #epsilons.append(asscalar(val / n_tmp - dot(point.x, tmp)/n_tmp**2))
                        epsilons.append(asscalar((val + dot(point.x, tmp))/n_tmp))
                        #epsilons.append(asscalar(val - dot(point.x, tmp))/n_tmp)
                        #epsilons.append(asscalar(val))
                        isConstraint.append(True)
                        points.append(point.x)
                        inactive.append(0)
                        nAddedVectors += 1
                        
                indToBeRemovedBySameAngle = []
                
                valDistances1 = asfarray(normed_values)
                valDistances2 = asfarray([(0 if isConstraint[i] else -F0) for i in range(nVec)]) / asfarray(subGradientNorms)
                valDistances3 = asfarray([dot(x-points[i], vec) for i, vec in enumerate(normedSubGradients)])
                
                valDistances = valDistances1 + valDistances2 + valDistances3

                
                #valDistances4 = asfarray([(0 if isConstraint[i] else -F0) for i in range(nVec)]) / asfarray(subGradientNorms)
                
                #valDistancesForExcluding = valDistances1 + valDistances3 + valDistances4 # with constraints it may yield different result vs valDistances
                
                if p.debug: p.debugmsg('valDistances: ' + str(valDistances))
                if iterInitialDataSize != 0:
                    for j in range(nAddedVectors):
                        ind = -1-j
                        scalarProducts = dot(normedSubGradients, normedSubGradients[ind])
                        IND = where(scalarProducts > 1 - self.sigma)[0]
                        if IND.size != 0:
                            _case = 1
                            if _case == 1:
                                mostUseful = argmax(valDistances[IND])
                                IND = delete(IND, mostUseful)
                                indToBeRemovedBySameAngle +=IND.tolist()
                            else:
                                indToBeRemovedBySameAngle += IND[:-1].tolist()

                indToBeRemovedBySameAngle = list(set(indToBeRemovedBySameAngle)) # TODO: simplify it
                indToBeRemovedBySameAngle.sort(reverse=True)

                if p.debug: p.debugmsg('indToBeRemovedBySameAngle: ' + str(indToBeRemovedBySameAngle) + ' from %d'  %nVec)
                if indToBeRemovedBySameAngle == range(nVec-1, nVec-nAddedVectors-1, -1) and ns > 5:
#                    print 'ns =', ns, 'hs =', hs, 'iterStartPoint.f():', iterStartPoint.f(), 'prevInnerCycleIterStartPoint.f()', prevInnerCycleIterStartPoint.f(), \
#                    'diff:', iterStartPoint.f()-prevInnerCycleIterStartPoint.f()
                    
                    #raise 0
                    p.istop = 17
                    p.msg = 'all new subgradients have been removed due to the angle threshold'
                    return
                                
                #print 'added:', nAddedVectors,'current lenght:', len(values), 'indToBeRemoved:', indToBeRemoved
                
                valDistances = valDistances.tolist()
                valDistances2 = valDistances2.tolist()
                for ind in indToBeRemovedBySameAngle:# TODO: simplify it
                    for List in StoredInfo + [valDistances, valDistances2]:
                        del List[ind]
                nVec -= len(indToBeRemovedBySameAngle)
               
                if nVec > nMaxVec:
                    for List in StoredInfo + [valDistances, valDistances2]:
                        del List[:-nMaxVec]
                    assert len(StoredInfo[-1]) == nMaxVec
                    nVec = nMaxVec
                    
                valDistances = asfarray(valDistances)
                valDistances2 = asfarray(valDistances2)
                
                #F = 0.0

                
                indActive = where(valDistances >= 0)[0]
                m = len(indActive)
                product = None

                #print('Ftol: %f   m: %d   ns: %d' %(Ftol, m, ns))
                #raise 0
                if p.debug: p.debugmsg('Ftol: %f     ns: %d' %(Ftol, ns))
                
                if nVec > 1:
                    normalizedSubGradients = asfarray(normedSubGradients)
                    product = dot(normalizedSubGradients, normalizedSubGradients.T)
                    
                    #best_QP_Point = None
                    
                    #maxQPshoutouts = 1
                    
                    for j in range(maxQPshoutouts if bestFeasiblePoint is not None else 1):
                        F = asscalar(bestFeasiblePoint.f() - Ftol * 5**j) if bestFeasiblePoint is not None else nan
                        valDistances2_modified = asfarray([(0 if isConstraint[i] else -F) for i in range(nVec)]) / asfarray(subGradientNorms)
                        ValDistances = valDistances +  valDistances2_modified - valDistances2
                        
                        # DEBUG!!!!!!!!!
                        #ValDistances = array([0, -1])
                        #ValDistances = valDistances
                        # DEBUG END!!!!!!!!!
                
                        # !!!!!!!!!!!!!            TODO: analitical solution for m==2
                        new = 0
                        if nVec == 2 and new:
                            a, b = normedSubGradients[0]*ValDistances[0], normedSubGradients[1]*ValDistances[1]
                            a2, b2, ab = (a**2).sum(), (b**2).sum(), dot(a, b)
                            beta = a2 * (ab-b2) / (ab**2 - a2 * b2)
                            alpha = b2 * (ab-a2) / (ab**2 - a2 * b2)
                            g1 = alpha * a + beta * b
                        else:
                            #projection, koeffs = PolytopProjection(product, asfarray(ValDistances), isProduct = True)   
                            #print 'before PolytopProjection'
                            koeffs = PolytopProjection(product, asfarray(ValDistances), isProduct = True, solver = self.qpsolver)
                            #print koeffs
                            #print 'after PolytopProjection'
                            projection = dot(normalizedSubGradients.T, koeffs).flatten()
                            #raise 0
#                            from openopt import QP
#                            p2 = QP(diag(ones(n)), zeros(n), A=-asfarray(normedSubGradients), b=-ValDistances)
#                            projection = p2.solve('cvxopt_qp', iprint=-1).xf
#                            print 'proj:', projection
#                            if itn != 0: raise 0
                            #if ns > 3: raise 0
                            threshold = 1e-9 # for to prevent small numerical issues
                            if j == 0 and any(dot(normalizedSubGradients, projection) < ValDistances * (1-threshold*sign(ValDistances)) - threshold):
                                p.istop = 16
                                p.msg = 'optimal solution wrt required Ftol has been obtained'
                                return
                                
                            #p.debugmsg('g1 shift: %f' % norm(g1/norm(g1)-projection/norm(projection)))
                            g1 = projection
                            #hs = 0.4*norm(g1)
                            M = norm(koeffs, inf)
                            # TODO: remove the cycles
                            indActive = where(koeffs >= M / 1e7)[0]
                            for k in indActive.tolist():
                                inactive[k] = 0
                        NewPoint = Point(x - g1)
                        #print 'isBetter:', NewPoint.betterThan(p.point(x), altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint)

                        if j == 0 or NewPoint.betterThan(best_QP_Point, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint): 
                            best_proj = g1
                            best_QP_Point = NewPoint
                        else:
                            g1 = best_proj
                            break
                            
                    maxQPshoutouts = max((j+2, 1))
                    #print 'opt j:', j, 'nVec:', nVec
                    #Xdist = norm(projection1)
    #                if hs < 0.25*Xdist :
    #                    hs = 0.25*Xdist

                else:
                    g1 = iterStartPoint._getDirection(self.approach, currBestFeasPoint = bestFeasiblePoint)
                    
                if any(isnan(g1)):
                    p.istop = 900
                    return                 
                    
                if any(g1): 
                    g1 /= p.norm(g1)
                else:
                    p.istop = 103 if Point(x).isFeas(False) else -103
                    #raise 0
                    return
                #hs = 1 

                """                           Forward line search                          """

                bestPointBeforeTurn = iterStartPoint
                
                hs_cumsum = 0
                hs_start = hs
                if not isinstance(g1, ndarray) or isinstance(g1, matrix):
                    g1 = g1.A.flatten()
                    
                hs_mult = 4.0
                for ls in xrange(p.maxLineSearch):
                    
#                    if ls > 20:
#                        hs_mult = 2.0
#                    elif ls > 10:
#                        hs_mult = 1.5
#                    elif ls > 2:
#                        hs_mult = 1.05
                    
                    assert all(isfinite(g1))
                    assert all(isfinite(x))
                    assert isfinite(hs)
                    x -= hs * g1
                    hs *= hs_mult
                    hs_cumsum += hs

                    newPoint = Point(x) #if ls == 0 else iterStartPoint.linePoint(hs_cumsum/(hs_cumsum-hs), oldPoint) #  TODO: take ls into account?
                    
                    if self.show_nnan: p.info('ls: %d nnan: %d' % (ls, newPoint.__nnan__()))
                    
                    if ls == 0:
                        oldPoint = iterStartPoint#prevIter_best_ls_point#prevIterPoint
                        oldoldPoint = oldPoint
                    assert all(isfinite(oldPoint.x))    
                    #if not self.checkTurnByGradient:
                    
                    #TODO: create routine for modifying bestFeasiblePoint
                    if newPoint.isFeas(True) and (bestFeasiblePoint is None or newPoint.f() > bestFeasiblePoint):
                        bestFeasiblePoint = newPoint
                            
                    if newPoint.betterThan(oldPoint, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint):
                        if newPoint.betterThan(bestPoint, altLinInEq=True): bestPoint = newPoint
                        oldoldPoint = oldPoint
                        #assert dot(oldoldPoint._getDirection(self.approach), g1)>= 0
                        oldPoint, newPoint = newPoint,  None
                    else:
                        bestPointBeforeTurn = oldoldPoint
                        if not itn % 4: 
                            for fn in ['_lin_ineq', '_lin_eq']:
                                if hasattr(newPoint, fn): delattr(newPoint, fn)
                        break

                #assert norm(oldoldPoint.x -newPoint.x) > 1e-17
                hs /= hs_mult
                if ls == p.maxLineSearch-1:
                    p.istop,  p.msg = IS_LINE_SEARCH_FAILED,  'maxLineSearch (' + str(p.maxLineSearch) + ') has been exceeded'
                    return

                p.debugmsg('ls_forward: %d' %ls)
                """                          Backward line search                          """
                maxLS = 500 #if ls == 0 else 5
                maxDeltaF = p.ftol / 16.0#Ftol/4.0 #p.ftol / 16.0
                maxDeltaX = p.xtol / 2.0 #if m < 2 else hs / 16.0#Xdist/16.0
                
                ls_backward = 0
                    
                #DEBUG
#                print '!!!!1:', isPointCovered(oldoldPoint, newPoint, bestFeasiblePoint, Ftol), '<<<'
#                print '!!!!2:', isPointCovered(newPoint, oldoldPoint, bestFeasiblePoint, Ftol), '<<<'
#                print '!!!!3:', isPointCovered(iterStartPoint, newPoint, bestFeasiblePoint, Ftol), '<<<'
#                print '!!!!4:', isPointCovered(newPoint, iterStartPoint, bestFeasiblePoint, Ftol), '<<<'
#                raise 0
                #DEBUG END
                
                #assert p.isUC
                maxRecNum = 400#4+int(log2(norm(oldoldPoint.x-newPoint.x)/p.xtol)) 
                #assert dot(oldoldPoint.df(), newPoint.df()) < 0
                #assert sign(dot(oldoldPoint.df(), g1)) != sign(dot(newPoint.df(), g1))
                point1, point2, nLSBackward = LocalizedSearch(oldoldPoint, newPoint, bestFeasiblePoint, Ftol, p, maxRecNum, self.approach)
                
                
                #assert sign(dot(point1.df(), g1)) != sign(dot(point2.df(), g1))
                best_ls_point = point1 if point1.betterThan(point2, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint) else point2

#                if self.doBackwardSearch:
#                    #print '----------------!!!!!!!!  norm(oldoldPoint - newPoint)', norm(oldoldPoint.x -newPoint.x)
#                    isOverHalphPi = True
#                    if isOverHalphPi:
#                        best_ls_point,  bestPointAfterTurn, ls_backward = \
#                        getBestPointAfterTurn(oldoldPoint, newPoint, maxLS = maxLS, maxDeltaF = p.ftol / 2.0, #sf = func, 
#                                            maxDeltaX = p.xtol / 2.0, altLinInEq = True, new_bs = True, checkTurnByGradient = True)
#                        #assert ls_backward != -7
#                    else:
#                        best_ls_point,  bestPointAfterTurn, ls_backward = \
#                        getBestPointAfterTurn(oldoldPoint, newPoint, maxLS = maxLS, maxDeltaF = p.ftol / 2.0, sf = func,  \
#                                            maxDeltaX = p.xtol / 2.0, altLinInEq = True, new_bs = True, checkTurnByGradient = True)       
#
#                    #assert best_ls_point is not iterStartPoint
#                    g1 = bestPointAfterTurn._getDirection(self.approach, currBestFeasPoint = bestFeasiblePoint)
##                    best_ls_point,  bestPointAfterTurn, ls_backward = \
##                    getBestPointAfterTurn(oldoldPoint, newPoint, maxLS = maxLS, maxDeltaF = maxDeltaF, sf = func,  \
##                                          maxDeltaX = maxDeltaX, altLinInEq = True, new_bs = True, checkTurnByGradient = True)
#                p.debugmsg('ls_backward: %d' % ls_backward)
#                if bestPointAfterTurn.betterThan(best_ls_point, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint):
#                    best_ls_point = bestPointAfterTurn
                if oldoldPoint.betterThan(best_ls_point, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint):
                    best_ls_point_with_start = oldoldPoint
                else:
                    best_ls_point_with_start = best_ls_point
                # TODO: extract last point from backward search, that one is better than iterPoint
                if best_ls_point.betterThan(bestPoint, altLinInEq=True): bestPoint = best_ls_point

                if best_ls_point.isFeas(True) and (bestFeasiblePoint is None or best_ls_point.betterThan(bestFeasiblePoint, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint)):
                    bestFeasiblePoint = best_ls_point

    #            print 'ls_backward', ls_backward

    #            if ls_backward < -4:
    #                Ftol /= 2.0
    #            elif ls > 4:
    #                Ftol *= 2.0
    #                
    #            print 'Ftol:', Ftol
                
                """                                 Updating hs                                 """
                step_x = p.norm(best_ls_point.x - prevIter_best_ls_point.x)
                step_f = abs(best_ls_point.f() - prevIter_best_ls_point.f())
                HS.append(hs_start)
                assert ls >= 0
                LS.append(ls)
                p.debugmsg('hs before: %0.1e' % hs)
#                if itn > 3:
#                    mean_ls = (3*LS[-1] + 2*LS[-2]+LS[-3]) / 6.0
#                    j0 = 3.3
#                    #print 'mean_ls:', mean_ls
#                    #print 'ls_backward:', ls_backward
#                    if mean_ls > j0:
#                        hs = (mean_ls - j0 + 1)**0.5 * hs_start
#                    else:
#                        #hs = hs_start / 16.0
#                        if (ls == 0 and ls_backward == -maxLS) or self.zhurb!=0:
#                            shift_x = step_x / p.xtol
#                            shift_f = step_f / p.ftol
#    #                        print 'shift_x: %e    shift_f: %e' %(shift_x, shift_f)
#                            RD = log10(shift_x+1e-100)
#                            if best_ls_point.isFeas(True) or prevIter_best_ls_point.isFeas(True):
#                                RD = min((RD, log10(shift_f + 1e-100)))
#                            #print 'RD:', RD
#                            if RD > 1.0:
#                                mp = (0.5, (ls/j0) ** 0.5, 1 - 0.2*RD)
#                                hs *= max(mp)

                prev_hs = hs
                if step_x != 0: 
                    hs = 0.5*step_x                  
#                elif ls  == 0 and nLSBackward > 4:
#                    hs /= 4.0
#                elif ls > 3:
#                    hs *= 2.0
                else:
                    hs = max((hs / 1e4,  p.xtol / 1e3))
                    #hs = max((p.xtol/100, 0.5*step_x))
                #print 'step_x:', step_x, 'new_hs:', hs, 'prev_hs:', prev_hs, 'ls:', ls, 'nLSBackward:', nLSBackward

                #if hs < p.xtol/4: hs = p.xtol/4
                
                """                            Handling iterPoints                            """
                   

                if itn == 0:
                    p.debugmsg('hs: ' + str(hs))
                    p.debugmsg('ls: ' + str(ls))
                if self.showLS: p.info('ls: ' + str(ls))
                if self.show_hs: p.info('hs: ' + str(hs))
                if self.show_nnan: p.info('nnan: ' + str(best_ls_point.__nnan__()))
                if self.showRes:
                    r, fname, ind = best_ls_point.mr(True)
                    p.info(fname+str(ind))
                    

                
                #print '^^^^1:>>', iterStartPoint.f(), '2:>>', best_ls_point_with_start.f()
                
                
                #hs = max((norm(best_ls_point_with_start.x-iterStartPoint.x)/2, 64*p.xtol))

                if p.debug: assert p.isUC

                
                prevInnerCycleIterStartPoint = iterStartPoint
                
                #if ns > 3: raise 0
                if best_ls_point_with_start.betterThan(iterStartPoint, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint):
                    #raise 0
                    ns = 0
                    iterStartPoint = best_ls_point_with_start
                    break
                else:
                    iterStartPoint = best_ls_point_with_start
                

                

#                if id(best_ls_point_with_start) != id(iterStartPoint): 
#                    print 'new iter point'
#                    assert iterStartPoint.f() != best_ls_point_with_start.f()
#                    if best_ls_point_with_start.betterThan(iterStartPoint, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint):
#                        #hs = norm(best_ls_point_with_start.x-iterStartPoint.x)/16#max(p.xtol, norm(best_ls_point_with_start.x-iterStartPoint.x)/160.0)
#                        ns = 0
#                        
#                        assert not iterStartPoint.betterThan(best_ls_point_with_start)
#                        
#                        iterStartPoint = best_ls_point_with_start
#                        
#                        assert p.isUC
#                        if iterStartPoint.f() - best_ls_point_with_start.f() > Ftol :                        
#                            break

#                    else:
#                        raise 0
                # !!!! TODO: has it to be outside the loop?
                
            # "while ns" loop end
            
            isOverHalphPi = product is not None and any(product[indActive].flatten() <= 0)

            if ns == self.ns and isOverHalphPi:
                p.istop = 16
                p.msg = 'Max linesearch directions number has been exceeded'
                best_ls_point = best_ls_point_with_start

            """                Some final things for gsubg main cycle                """
            prevIter_best_ls_point = best_ls_point_with_start
            
            
            # TODO: mb move it inside inner loop
            if koeffs is not None:
                indInactive = where(koeffs < M / 1e7)[0]
                for k in indInactive.tolist():
                    inactive[k] += 1
                indInactiveToBeRemoved = where(asarray(inactive) > 5)[0].tolist()                    
#                print ('indInactiveToBeRemoved:'+ str(indInactiveToBeRemoved) + ' from' + str(nVec))
                if p.debug: p.debugmsg('indInactiveToBeRemoved:'+ str(indInactiveToBeRemoved) + ' from' + str(nVec))
                if len(indInactiveToBeRemoved) != 0: # elseware error in current Python 2.6
                    indInactiveToBeRemoved.reverse()# will be sorted in descending order
                    nVec -= len(indInactiveToBeRemoved)
                    for j in indInactiveToBeRemoved:
                        for List in StoredInfo:# + [valDistances.tolist()]:
                            del List[j]     

                
            """                               Call OO iterfcn                                """
            if hasattr(p, '_df'): delattr(p, '_df')
            if best_ls_point.isFeas(False) and hasattr(best_ls_point, '_df'): 
                p._df = best_ls_point.df().copy()           
            assert all(isfinite(best_ls_point.x))
#            print '--------------'
#            print norm(best_ls_point.x-p.xk)
            #if norm(best_ls_point.x-p.xk) == 0: raise 0
            
            cond_same_point = array_equal(best_ls_point.x, p.xk)
            p.iterfcn(best_ls_point)
            #p.iterfcn(bestPointBeforeTurn)

            """                             Check stop criteria                           """

            if cond_same_point and not p.istop:
                #raise 0
                p.istop = 14
                p.msg = 'X[k-1] and X[k] are same'
                p.stopdict[SMALL_DELTA_X] = True
                return
            
            s2 = 0
            if p.istop and not p.userStop:
                if p.istop not in p.stopdict: p.stopdict[p.istop] = True # it's actual for converters, TODO: fix it
                if SMALL_DF in p.stopdict:
                    if best_ls_point.isFeas(False): s2 = p.istop
                    p.stopdict.pop(SMALL_DF)
                if SMALL_DELTA_F in p.stopdict:
                    # TODO: implement it more properly
                    if best_ls_point.isFeas(False) and prevIter_best_ls_point.f() != best_ls_point.f(): s2 = p.istop
                    p.stopdict.pop(SMALL_DELTA_F)
                if SMALL_DELTA_X in p.stopdict:
                    if best_ls_point.isFeas(False) or not prevIter_best_ls_point.isFeas(False) or cond_same_point: s2 = p.istop
                    p.stopdict.pop(SMALL_DELTA_X)
#                if s2 and (any(isnan(best_ls_point.c())) or any(isnan(best_ls_point.h()))) \
#                and not p.isNaNInConstraintsAllowed\
#                and not cond_same_point:
#                    s2 = 0
                    
                if not s2 and any(p.stopdict.values()):
                    for key,  val in p.stopdict.iteritems():
                        if val == True:
                            s2 = key
                            break
                p.istop = s2
                
                for key,  val in p.stopdict.iteritems():
                    if key < 0 or key in set([FVAL_IS_ENOUGH, USER_DEMAND_STOP, BUTTON_ENOUGH_HAS_BEEN_PRESSED]):
                        #p.iterfcn(bestPoint)
                        return
            """                                If stop required                                """
            
            if p.istop:
                    #p.iterfcn(bestPoint)
                    return

isPointCovered2 = lambda pointWithSubGradient, pointToCheck, bestFeasiblePoint, Ftol, contol:\
    pointWithSubGradient.f() - bestFeasiblePoint.f() + 0.75*Ftol > dot(pointWithSubGradient.x - pointToCheck.x, pointWithSubGradient.df())

def isPointCovered3(pointWithSubGradient, pointToCheck, bestFeasiblePoint, Ftol, contol):
    if bestFeasiblePoint is not None \
    and pointWithSubGradient.f() - bestFeasiblePoint.f() + 0.75*Ftol > dot(pointWithSubGradient.x - pointToCheck.x, pointWithSubGradient.df()):
        return True
    if not pointWithSubGradient.isFeas(True) and \
    pointWithSubGradient.mr_alt() + 1e-15 > \
    dot(pointWithSubGradient.x - pointToCheck.x, pointWithSubGradient._getDirection('all active', currBestFeasPoint = bestFeasiblePoint)):
        return True
    return False

def isPointCovered4(pointWithSubGradient, pointToCheck, bestFeasiblePoint, Ftol, contol):
    if not pointWithSubGradient.isFeas(True):
        if  pointWithSubGradient.mr_alt(bestFeasiblePoint = bestFeasiblePoint) + 0.5*contol > \
            dot(pointWithSubGradient.x - pointToCheck.x, pointWithSubGradient._getDirection('all active')):#, currBestFeasPoint = bestFeasiblePoint)):
            return True
            #pass
        else:
            return False
    elif pointWithSubGradient.f() - bestFeasiblePoint.f() + 0.75*Ftol > dot(pointWithSubGradient.x - pointToCheck.x, pointWithSubGradient.df()):
        # if pointWithSubGradient is feas (i.e. not 1st case) than bestFeasiblePoint is not None
        return True
        
    return False

isPointCovered = isPointCovered4

def LocalizedSearch(point1, point2, bestFeasiblePoint, Ftol, p, maxRecNum, approach):
    contol = p.contol
    for i in range(maxRecNum):
        if p.debug:
            p.debugmsg('req num: %d from %d' % (i, maxRecNum))

        new = 0
        if new:
            if point1.betterThan(point2, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint) and isPointCovered(point2, point1, bestFeasiblePoint, Ftol) \
            or point2.betterThan(point1, altLinInEq=True, bestFeasiblePoint = bestFeasiblePoint) and isPointCovered(point1, point2, bestFeasiblePoint, Ftol):
                break
        else:
            isPoint1Covered = isPointCovered(point2, point1, bestFeasiblePoint, Ftol, contol)
            isPoint2Covered = isPointCovered(point1, point2, bestFeasiblePoint, Ftol, contol)
            #print 'isPoint1Covered:', isPoint1Covered, 'isPoint2Covered:', isPoint2Covered
            if isPoint1Covered and isPoint2Covered:# and i != 0:
                break
        
        # TODO: prevent small numerical errors accumulation
        point = point1.linePoint(0.5, point2)
        #point = p.point((point1.x + point2.x)/2.0) 
        
        
        if point.isFeas(True) and (bestFeasiblePoint is None or bestFeasiblePoint.f() > point.f()):
            bestFeasiblePoint = point
        
        if p.debug: assert p.isUC
        if dot(point._getDirection(approach, currBestFeasPoint = bestFeasiblePoint), point1.x-point2.x) < 0:
            point2 = point
        else:
            point1 = point
        
#        Point = point1 if dot(point.df(), point1.x-point2.x) < 0 else point2
#        #assert sign(dot(point.df(), point1.x-point2.x)) != sign(dot(Point.df(), point1.x-point2.x))
#        
#
#        return LocalizedSearch(point, Point, bestFeasiblePoint, Ftol, p, maxRecNum-1)
    return point1, point2, i
    
#    if isPoint1Covered and not isPoint2Covered:
#        return LocalizedSearch(point, point2, bestFeasiblePoint, Ftol, p, maxRecNum-1)
#    elif isPoint2Covered and not isPoint1Covered:
#        return LocalizedSearch(point, point1, bestFeasiblePoint, Ftol, p, maxRecNum-1)
#    else:
#        # TODO: check sign
#        
#        return LocalizedSearch(point, Point, bestFeasiblePoint, Ftol, p, maxRecNum-1)
        
        
        
######################33
    #                    from scipy.sparse import eye
    #                    from openopt import QP            
    #                    projection2 = QP(eye(p.n, p.n), zeros_like(x), A=polyedr, b = -valDistances).solve('cvxopt_qp', iprint = -1).xf
    #                    g1 = projection2
