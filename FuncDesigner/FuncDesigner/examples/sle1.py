"""
"Hello world" example 
for solving SLE (system of linear equations)
"""
from FuncDesigner import *

# create some variables
a, b, c = oovars('a', 'b', 'c')
# or just a, b, c = oovars(3)

# Python list of 3 linear equations with 3 variables
f = [2*a+3*b-2*c+5, 2*a+13*b+15, a+4*b+2*c-45]
# alternatively, you could pass equations:
#f = [(2*a+3*b-2*c).eq(-5), (2*a+15).eq(-13*b), a.eq(-4*b-2*c+45)]
# assign SLE
linSys = sle(f)

r = linSys.solve()

# print result
print r
# Expected output:
# {b: array([-5.]), a: array([ 25.]), c: array([ 20.])}
