#! /usr/bin/env python

## 
## Copyright (c) 2011, 2015, 2020 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the 
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

# All this for __main__ below
import os
import sys
import traceback
import string
import time

from numpy import *

def pchip(x,y,xx,expected_index=None): # pchip_m
    """Interpolate xx using piecewise cubic Hermite polynomials based on x, y
    Input:
    	x - input array of real x values, assumed ascending 
        y - input array of real y values corresponding to xi values
        xx - input array of real x points to interpolate

    Returns:
    	yy - interpolated values of x

    Raises:
    
                
    References:
       Author:   David K. Kahaner,   National Bureau of Standards
       From the book "Numerical Methods and Software" by
       D. Kahaner, C. Moler, and S. Nash
       Prentice Hall, 1988
   
       Fritsch, F. N.;     and R.E. Carlson.
       "Monotone Piecewise Cubic Interpolation"
       SIAM J. Numer. Anal. 17, 2 (April 1980), 238 - 246
   
       Fritsch, F. N.;     and J. Butland.
       "A Method for Constructing Local Monotone Piecewise Cubic Interpolants"
       Lawrence Livermore National Laboratory
       Preprint UCRL-87559 (April 1982)
   
       De Boor, Carl.
       "A Practical Guide to Splines"
       Springer-Verlag, New York
       1978
   
       Fritsch, F. N.
       "Piecewise Cubic Hermite Interpolation Package, Final Specifications"
       Lawrence Livermore National Laboratory
       Computer Documentation UCID-30194
       August 1982
   
       Based on matlab source, partially evaluated for vectors x,y,xx
       /Applications/MATLAB_R2007b/toolbox/matlab/polyfun/...
    """
    if (len(xx) == 0): # anything to do?
        return []
    # Matlab works with transposed arrays.  We don't in this version.
    # M: x = x';
    # M: y = y';
    # M: xx = xx';
    # NOTE: if we are passed x or y as integers division computations for w1 and w2 expressions lead to zeros and hence bad answers
    x = array(x, float64); y = array(y, float64); xx = array(xx, float64)
    # M: pchip.m
    # M: n = length(x); h = diff(x); m = prod(sizey);
    n = len(x)
    # hard-wired offsets adjusted for 0-based rather than 1-based indexing
    # In the following we convert to python addressing by changing n+/-x to nn+/-x
    nn = n - 1 # last addressible index in x and y, etc. (would be n for matlab).
    h = diff(x)
    # UNUSED M: m = 1 # m = prod(sizey)  = prod(1) = 1
    sizey = len(y) # size(y) != length(y) in general for matlab but it is the case for vectors
    # NOTE: Renamed del in original to delta here to avoid del() python function
    # M: delta = diff(y,1,2)./repmat(h,m,1);
    # M: delta = diff(y,1,2)./h;
    delta = diff(y)/h
    d = zeros(sizey)
    # M: d = pchipslopes(x,y,delta); % open-coded function call
    if (n == 2):
        # M: d = repmat(delta(1),size(y)); # replicate delta(1) and tile size(y) times
        d = delta[0]*ones(sizey) # equivalent?
    else:
        #  Slopes at interior points.
        #  d(k) = weighted average of delta(k-1) and delta(k) when they have the same sign.
        #  d(k) = 0 when delta(k-1) and delta(k) have opposites signs or either is zero.

        # DONE see above M: d = zeros(size(y));
        k = [] # initialize in scope
        if all(isreal(delta)):
            # M: k = find(sign(delta(1:n-2)).*sign(delta(2:n-1)) > 0)
            k = nonzero(sign(delta[0:n-2])*sign(delta[1:n-1]) > 0)
        else:
            # M: k = find(~(delta(1:n-2) == 0 & delta(2:n-1) == 0))
            k = nonzero(not(delta[0:n-2] == 0 and delta[2:n-1] == 0))
        k = k[0] # fetch equivalent python result; where we changed inflection
        # CONSIDER k1 = k+1
        # DONE see above M: h = diff(x)
        # M: hs = h(k)+h(k+1)
        hs = h[k]+h[k+1]
        # CONSIDER hs3 = 3*hs subexpression
        # M: w1 = (h(k)+hs)/(3*hs)
        w1 = (h[k]+hs)/(3*hs)
        # M: w2 = (hs+h(k+1))/(3*hs)
        w2 = (hs+h[k+1])/(3*hs)
        # M: dmax = max(abs(delta(k)), abs(delta(k+1)))
        dmax = maximum(abs(delta[k]), abs(delta[k+1]))
        # M: dmin = min(abs(delta(k)), abs(delta(k+1)))
        dmin = minimum(abs(delta[k]), abs(delta[k+1]))
        # M: cc = w1*(delta(k)/dmax) + w2*(delta(k+1)/dmax)
        cc = w1*(delta[k]/dmax) + w2*(delta[k+1]/dmax)
        # Is cc ever complex for our application?  Shouldn't be....
        # M: d(k+1) = dmin/conj(cc)
        d[k+1] = dmin/conjugate(cc)

        #  Slopes at end points.
        #  Set d(1) and d(n) via non-centered, shape-preserving three-point formulae.

        # M: d(1) = ((2*h(1)+h(2))*delta(1) - h(1)*delta(2))/(h(1)+h(2));
        d[0] = ((2*h[0]+h[1])*delta[0] - h[0]*delta[1])/(h[0]+h[1]);
        # M: if isreal(d) && (sign(d(1)) ~= sign(del(1)))
        if all(isreal(d)) and (sign(d[0]) != sign(delta[0])):
            # M: d(1) = 0
            d[0] = 0
        # M: elseif (sign(del(1)) ~= sign(del(2))) && (abs(d(1)) > abs(3*del(1)))
        elif (sign(delta[0]) != sign(delta[1])) and (abs(d[0]) > abs(3*delta[0])):
            # M: d(1) = 3*delta(1)
            d[0] = 3*delta[0]

        # M: d(n) = ((2*h(n-1)+h(n-2))*delta(n-1) - h(n-1)*delta(n-2))/(h(n-1)+h(n-2))
        d[nn] = ((2*h[nn-1]+h[nn-2])*delta[nn-1] - h[nn-1]*delta[nn-2])/(h[nn-1]+h[nn-2])
        # M: if isreal(d) && (sign(d(n)) ~= sign(del(n-1)))
        if all(isreal(d)) and (sign(d[nn]) != sign(delta[nn-1])):
            # M: d(n) = 0
            d[nn] = 0
        # M: elseif (sign(del(n-1)) ~= sign(del(n-2))) && (abs(d(n)) > abs(3*del(n-1)))
        elif (sign(delta[nn-1]) != sign(delta[nn-2])) and (abs(d[nn]) > abs(3*delta[nn-1])):
            # M: d(n) = 3*delta(n-1);
            d[nn] = 3*delta[nn-1];

    # M: v = pwch(x,y,d,h,delta); # DEAD sizey = 1: v.dim = sizey;
    # v is an object describing a polynomical of order 4 with breaks = x,# v.coeffs = <computed by pwch>
    # handle pwch argument assignments
    s = d # slopes
    dx = h # diff(x)
    divdif = delta
    # NOTE: d redefinition
    # M: d = size(y,1) # vector implies d = [1]
    d = 1 # NOT sizey!!
    # M: dxd = repmat(dx,d,1)
    dxd = dx
    # M: dzzdx = (divdif-s(:,1:n-1))/dxd
    dzzdx = (divdif-s[0:n-1])/dxd
    # M: dzdxdx = (s(:,2:n)-divdif)/dxd
    dzdxdx = (s[1:n]-divdif)/dxd
    # M: dnm1 = d*(n-1)
    dnm1 = d*(nn) # this is a dimension, not a value
    # M: c = [reshape((dzdxdx-dzzdx)/dxd,dnm1,1),reshape(2*dzzdx-dzdxdx,dnm1,1),reshape(s(:,1:n-1),dnm1,1),reshape(y(:,1:n-1),dnm1,1)]
    c = array([reshape((dzdxdx-dzzdx)/dxd, dnm1),
               reshape(2*dzzdx-dzdxdx, dnm1),
               reshape(s[0:nn], dnm1),
               reshape(y[0:nn], dnm1)])
    k = 4 # order
    # end pwch
    # M: yy = ppval(v,xx); # interpolate xx by fitting polynomical described by v
    b = x # CONSIDER no duplication
    # M: l = n - 1 # pieces
    l = nn # pieces (a dimension)
    # M: [ignore, index] = histc(xx,[-inf,b(2:l),inf]); # M: find the indices in b where each xx is closest
    # b(2:l) => b(2:n-1) implies we write over the first and last element with -inf/+inf
    bins = array(b); bins[0] = -inf; bins[-1] = inf # bins (aka x) are ensured to be float so this never generates OverflowError
    # Completely lucky find: numpy.searchsorted, which reports the indices where elements of xx need to be inserted in bins to preserve the order of bins
    index = searchsorted(bins, xx, side='right') # NOT side='left' sg144 jun08 dive 53 fails in first salin pchip calc with first point
    index -= 1 # searchsorted returns indices are for the right-most edge of bins correctly but we need 'leftmost'
        
    if (expected_index is not None):
        pass # eventually compare index w/ expected index....from matlab dumps
    
    # M: sizexx = size(xx); lx = numel(xx); xs = reshape(xx,1,lx); # xs == xx
    # M: xs = xs-b(index);
    xs = xx-b[index] # go to local coordinates...offsets of each xx from the nearest x (at index)
    # ... and apply nested multiplication, evaluating the coefficents of the 4th-order fitted polynomials on the offsets at index
    yy = c[0][index] # was M: c(index,1)
    for i in range(1, k): # M: was 2:k
        yy = xs*yy + c[i][index]
    # end ppval
    return yy

def pchip_test(x,y,xx,yy,index=None):
    yy_computed = pchip(x, y, xx, index)
    diff_yy = yy - yy_computed
    if (max(abs(diff_yy)) > 0.0001):
        print('Differences!') # beyond printing resolution
    else:
        print('Good!')
    return None

def main():
    y_new = pchip_test([0.5, 1., 2., 3., 4., 5.],
                       [0.25, 1., 4., 9., 16., 25.],
                       [1., 4., 6., -2.],
                       [1.0000,   16.0000,   35.7500,    9.3571], # !! note -2 value
                       )

    y_new = pchip_test([-3., -2., -1., 0, 1., 2., 3.],
                       [-1., -1., -1., 0, 1., 1., 1.],
                       [3.01, 2.5, -3.1, 0.5, 0.8, 0.9, 1.1, 2.0, 2.1],
                       [1.0000, 1.0000, 1.0000, 0.6250, 0.9280, 0.9810, 1.0000, 1.0000, 1.0000],
                       )

    return None

if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove('--profile')
            profile_file_name = os.path.splitext(os.path.split(sys.argv[0])[1])[0] + '_' \
                + Utils.ensure_basename(time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))) + ".cprof"
            # Generate line timings
            retval = cProfile.run("main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats('time', 'calls')
            stats.print_stats()
        else:
            retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
