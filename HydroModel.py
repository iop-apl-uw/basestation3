#! /usr/bin/env python

## 
## Copyright (c) 2006-2022 by University of Washington.  All rights reserved.
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

"""Contains the seaglider hydro-dynamic model
"""
from numpy import *
import math
import Utils
from BaseLog import *
import warnings

# from TraceArray import * # REMOVE use this only only if we are tracing/comparing computations w/ matlab
# physical constants
gravity = 9.82 # m/s2
g2kg = 0.001 # grams to kgs
m2cm = 100 # m to cm
cm2m = 0.01 # cm to m

def find_stalled(speed_v, vehicle_pitch_degrees_v, num_rows, calib_consts):
    '''Determine where stalled
    Inputs:
    speed_v -- glider speeds
    vehicle_pitch_degrees_v -- vehicle pitch
    num_rows -- size of speed vector
    calib_consts - calibration constants

    Outputs:
    stalled_i_v - indices of any stall points
    '''
    # what about speed_v[i].imag ## get the imaginary part...
    max_stall_speed = calib_consts['max_stall_speed']
    min_stall_angle = calib_consts['min_stall_angle']
    min_stall_speed = calib_consts['min_stall_speed']
    # (speed_v >= max_stall_speed and vehicle_pitch_degrees_v < min_stall_angle) or speed_v <= min_stall_speed
    stalled_i_v = union1d(intersect1d(where(speed_v >= max_stall_speed)[0], where(vehicle_pitch_degrees_v < min_stall_angle)[0]), where(speed_v <= min_stall_speed)[0])
    return stalled_i_v.tolist()

## NOTE: the q^(1/4) factor (at least) used below is based on the original SG shape
## With the new ogive fairing on DG and possibly SG this factor will change, perhaps to sqrt(q) instead.
## This will yield new simplified eqns in both functions....

## NOTE: There are typos in the Eriksen paper:
## Missing a square term for D on B^2 eqn last para pg 425:
## Should be: B^2 = D^2 + L^2
## Also the typesetting is confusing on defn of q, same page:
## q = (rho/2)*(U^2 + W^2) = (rho/2)*total_velocity^2
## Eqn 8 on pg 426, the leading term should be -a/2c not -alpha/2c
## Eqn 8 should also read ... (1 - sqrt(1 -/+ 4/(Lambda*tan2(theta)))), not +/- (hence the sign flip below)

# GSM is the simplified hydrodynamic flight model that neglects buoyancy except via q^s
# Instead it assumes that attack angle is a weak function of dynamic pressure q.

# With that assumption, the attack angle alpha can be computed (iteratively) using
#
#   alpha = (-a/2c)*tan(pitch-alpha)*(1 - sqrt(1 - (4bcq^s/a^2tan^2(pitch-alpha))))
#
# where
#
#   q = (rho0/2)(w^2/sin^2(pitch - alpha)

# Since we measure w and pitch we can solve the above for alpha (iteratively,
# assuming alphas is zero to begin with) and then, given that q = (rho/2)*(u^2 +
# w^2), we can solve for the glider speed u and the glide slope.

# HOWEVER, w often reflects internal waves, etc. as well as the steady flight
# vertical rate so u won't reflect the steady-state glider speed. Further the
# glider speeds returned depend on a/b/c suppied so you need good estimates of
# those.  GSM, however, can't provide them since every a/b/c combination passed
# to glide_slope() will provide *some* speed u such that w is precisely matched.
# To estimate a/b/c you do need to estimate buoyancy forcing and hence the speed
# in still water and then you can see variations in measured w indicating
# internal waves; this requires the use of HDM below.  GSM is thus used after
# you have a reasonable a/b/c to get a crude estimate of speeds and when you
# have suspect buoyancy calculations (because of mis-estimated volmax, for
# example).  It is also sufficent for glider onboard estimates of speeds and
# hence DAC for navigation.  GSM is not good for scientific analysis based on
# velocities or displacements.

# CONSIDER rename glider_slope to pressure_pitch_model
## NOTE Talking w/ CCE 9/21/09 about rho0 he claims it is the density at which the drag was measured
# (and so is a reference point), not the assumed max density, hence buoyancy on the glider.  We need
# to review these calculations to make sure we are using it properly.
# Also, even if rho0 changed the range is between 1023 and 1027 or 5 parts in 1000 or .5% difference over the dive range
# which is small.


# flightvec0 goes from 0 to 15 
loop_count = 21 # bin_fit 'glideslope' goes from 1 to 20
loop_count = 41 # TestData/sg144_ps_022613/p144* dives have a few points that take a while to converge but they do...
def glide_slope(w_cm_s_v, vehicle_pitch_rad_v, calib_consts):
    """
    Compute the glide slope, base on observed vertical velocity (pressure change), vehicle pitch,
    and hydrodynamic constants.  Assumes constant bouyancy throught the dive (rho0)

    Input:               
        w - (observed) vertical velocity cm/s
        pitch - observed vehicle pitch (radians, positive nose up)
        calib_consts - that contain
    			hd_a, hd_b, hd_c - hydrodynamic parameters for lift, drag, and induced drag
                        rho - density of deep water (maximum density encountered)

    Returns:
        converged - whether the iterative solution converged
        speed - total vehicle speed through the water (cm/s)
        glide angle - radians, positive nose up
        stalled_i_v - locations where stalled
        
    Raises:
      Any exceptions raised are considered critical errors and not expected
    """

    num_rows = len(w_cm_s_v)
    hd_a = calib_consts['hd_a']
    hd_b = calib_consts['hd_b']
    hd_c = calib_consts['hd_c']
    hd_s = calib_consts['hd_s'] # how the drag scales by shape
    rho0 = calib_consts['rho0']
    # No use of glider_length since not using buoyancy terms for lift/drag

    # Compute initial total speed (u_initial_cm_s_v) based on observed pitch and vertical velocity
    u_initial_cm_s_v = zeros(num_rows, float)
    pitched_i_v = where(array(vehicle_pitch_rad_v) != 0.0)[0]
    u_initial_cm_s_v[pitched_i_v] = w_cm_s_v[pitched_i_v]/sin(vehicle_pitch_rad_v[pitched_i_v])

    # Compute constants used in hydrodynamic computations (for efficiency)
    # These are used to compute the (inverted) performance factor (param) under the sqrt in Eqn 8
    # 4/lambda*tan^2(theta), where lambda here incorporates a constant q
    cx = 4.*hd_b*hd_c
    cy = hd_a*hd_a*math.pow(rho0/2.0, -hd_s)
    cz = cy/cx
    czr = cx/cy

    # Compute performance factor based on constant bouyancy
    # We do this once to compute where the vehicle is flying (non-complex solns)
    # NOTE: defn: q = (rho/2)*u^2 where u is estimated total velocity
    # Thus, q^(-1/4) = (rho0/2)^(1/4)*(cm2m*u)^(2/4) = (rho0/2)^(1/4)*sqrt(cm2m*u)
    perf_fac_v = tan(vehicle_pitch_rad_v)*tan(vehicle_pitch_rad_v)*sqrt(cm2m*fabs(u_initial_cm_s_v))*cz

    # Establish (initial) masks for stall versus non-stall values
    # these are updated with additional stall points below
    flying_v = zeros(num_rows, float) # assume all stalled
    non_stalled_i_v = [i for i in range(num_rows) if perf_fac_v[i] > 1]
    flying_v[non_stalled_i_v] = 1; # flying

    # First, initialize counter and test delta
    theta_rad_v = array(vehicle_pitch_rad_v)

    # Iterate on glide angle until convergence or loop limit
    converged = False # assume the worst
    for loop_counter in range(loop_count): 
        theta_prev_rad_v = array(theta_rad_v)  # Store the previous iteration
        max_delta_theta = 0.
        for i in range(num_rows):
            if(w_cm_s_v[i] * math.sin(theta_rad_v[i]) < 0.0):
                flying_v[i] = 0 # stalled
                
            delta_theta = 0.
            if flying_v[i]:
                # compute non-inverted "param" for Eqn 8
                factor = czr*(1.0/(math.tan(theta_rad_v[i])*math.tan(theta_rad_v[i])*math.sqrt(cm2m*w_cm_s_v[i]/math.sin(theta_rad_v[i]))))
                if factor <= 1.0:
                    # flying; compute attack angle (alpha) using Eqn 8.  Eqn 7 ignored because of constant bouyancy assumption
                    # minus sign critical here
                    alpha = (-0.5*hd_a*math.tan(theta_rad_v[i])*(1.0 - math.sqrt(1.0 - factor)))/hd_c
                    # improve our guess about glide angle based on new attack angle
                    # defn: pitch = glide_angle + attack-angle
                    theta_rad_v[i] = vehicle_pitch_rad_v[i] - math.radians(alpha)
                    delta_theta = theta_prev_rad_v[i] - theta_rad_v[i]
                else:
                    delta_theta = 0.
                    flying_v[i] = 0. # stalled
            else:
                delta_theta = 0.

            max_delta_theta = max(fabs(delta_theta), max_delta_theta)
        # end of i loop, now check for any improvement in the estimates of theta_rad_v
        log_debug("GSM iteration %d max delta theta = %f" % (loop_counter, max_delta_theta))
        if max_delta_theta < 0.0001: # [rad]
            converged = True
            break
    # end of loop_counter loop

    # NOTE this correction isn't in diveplot_func.m
    # Where model has singularities (flying_v[i] = 0), set theta_rad_v = pitch angle for computation below
    stalled_i_v = where(flying_v == 0)[0]
    theta_rad_v[stalled_i_v] = vehicle_pitch_rad_v[stalled_i_v]

    total_speed_cm_s_v = zeros(num_rows, float) # assume stalled everywhere....
    pitched_i_v = where(vehicle_pitch_rad_v != 0.0)[0]
    total_speed_cm_s_v[pitched_i_v] = fabs(w_cm_s_v[pitched_i_v]*sqrt(1. + (1./(tan(theta_rad_v[pitched_i_v])**2)))) # except here...

    # Determine other stalls...
    stalled_i_v = find_stalled(total_speed_cm_s_v, degrees(vehicle_pitch_rad_v), num_rows, calib_consts)
    total_speed_cm_s_v[stalled_i_v] = 0 # mark as stall
    theta_rad_v[stalled_i_v] = 0 # going nowhere (this nails the pitch angle assignment above)
    return (converged, total_speed_cm_s_v, theta_rad_v, stalled_i_v)

# CONSIDER rename hydro_model to buoyancy_pitch_model
def hydro_model(buoyancy_v, vehicle_pitch_degrees_v, calib_consts):
    """Compute vehicle speed and glide angle from buoyancy and observed pitch

    Usage: converged,umag,theta,stalled_i_v = hydro_model(buoyancy_v, vehicle_pitch_degrees_v, calib_consts)
 
    Input:               
        buoyancy_v - n_pts vector (grams, positive is upward)
        vehicle_pitch_degrees_v - observed vehicle pitch (degrees (! not radians), positive nose up)
        calib_consts - that contain
           hd_a, hd_b, hd_c - hydrodynamic parameters for lift, drag, and induced drag
           hd_s - how drag scales by shape
           rho - density of deep water (maximum density encountered)
           glider_length - the length of the vehicle

    Returns:
        converged - whether the iterative solution converged
        theta - glide angle in radians, positive nose up
        umag - total vehicle speed through the water (cm/s)
        stalled_i_v - locations where stalled
 
    Reference: 
       flightvec0.m (CCE)
       Eriksen, C. C., et al: IEEE Journal of Oceanic Engineering, v26, no.4, October, 2001.

    hd_a is in 1/deg. units, hd_b has dimensions q^(1/4), hd_c is in 1/deg.^2 units
    """

    # Size of the vectors
    num_rows = len(buoyancy_v)
    hd_a = calib_consts['hd_a']
    hd_b = calib_consts['hd_b']
    hd_c = calib_consts['hd_c']
    hd_s = calib_consts['hd_s'] # how the drag scales by shape
    rho0 = calib_consts['rho0']
    glider_length = calib_consts['glider_length']

    assert(hd_b != 0.0)
    assert(hd_s != -1.0)

    # trace_comment('hd_a = %f' % hd_a);
    # trace_comment('hd_b = %f' % hd_b);
    # trace_comment('hd_c = %f' % hd_c);
    # trace_comment('hd_s = %f' % hd_s);
    # trace_comment('glider_length = %f' % glider_length);
    # trace_comment('rho0 = %f' % rho0);
    # trace_array('buoyancy', buoyancy_v)
    # trace_array('pitch', vehicle_pitch_degrees_v)

    # Compute constants used in hydrodynamic computations (for efficiency)
    # These are used to compute the (inverted) performance factor (param) under the sqrt in Eqn 8
    l2 = glider_length*glider_length
    l2_hd_b2 = 2.0*l2*hd_b
    hd_a2 = hd_a*hd_a
    hd_bc4 = 4.0*hd_b*hd_c
    hd_c2 = 2.0*hd_c

    buoyancy_sign_v = sign(buoyancy_v) # never non-zero
    pitched_i_v = where(array(vehicle_pitch_degrees_v) != 0.0)[0]
    pitch_sign_v = ones(num_rows, float) # if flat, assume sign is 1.0
    pitch_sign_v[pitched_i_v] = sign(vehicle_pitch_degrees_v[pitched_i_v])
    # Compute points where flight is expected: where buoyancy and pitch are both up or both down
    buoyancy_pitch_ok_v = zeros(num_rows, float)
    buoyancy_pitch_ok_v[where(array(buoyancy_sign_v*pitch_sign_v) > 0.0)[0]] = 1.0
    buoyancy_pitch_ok_v = buoyancy_pitch_ok_v.tolist()
    # compute buoyancy force from buoyancy F = ma = (g)*(g2kg)*(m/s)^2 [Newtons]
    buoyancy_force_v = buoyancy_v*g2kg*gravity

    # Initially assume the glide angle (theta) is +/-pi/4 radians (45 degrees) (climb or dive, respectively)
    # We iterate below to determine the actual glide slope
    theta = (math.pi/4.0)*buoyancy_sign_v
    
    # Compute initial dynamic pressure q for vertical flight 
    # Initial q is determined from the drag eqn. (Eqn. 2 in Eriksen et al.) by assuming attack angle alpha = 0
    # and that we are completely vertical (sin(90) = 1) so all drag, no lift
    # This always a positive quantity thanks to the buoyancy_sign_v value above
    # We deliberately start far away from the soln so both q and th, set independently here,
    # are able to relax together to a consistent soln.

    # BUG: Depending on initial abc values this formulation of 'q_old' will be arbitrarily close to q below
    # and terminate the loop after a single iteration with poor th (and q).  
    # If the loop is forced to run at least twice, both q and th are updated and we make proper progress toward the soln.
    # In particular, this problematic initial q expression from flightvec2 triggers the problem with more regularity.
    # DEAD q = power((buoyancy_force_v*sin(theta))/(l2*hd_b), 1/(1+hd_s))

    # This original version, without the sin(th) term, ensures q and q_old are sufficiently different
    # that we don't stall out the loop; nevertheless we ensure two loops below to get q close first, then th
    q = power(buoyancy_sign_v*buoyancy_force_v/(l2*hd_b), 1/(1+hd_s)) # dynamic pressure for vertical flight
    # trace_array('q_init', q)

    # This loop iterates the dynamic pressure (q) to get glidespeed 
    # and the attack angle (alpha) to get glideangle (theta)
    # buoyancy is taken to be an accurately known quantity and is not iterated here (but see caller)
    # We iterate a fixed number of times but break early if our max % difference is less that residual_test
    converged = False # assume the worst
    residual_test = 0.001   # loop completion test value
    for j in range(loop_count): 
        q_prev = array(q) # copy q
        
        # discriminant_inv is the reciprocal of the term subtracted 
        # from 1 under the radical in the solution equations (Eqs. 7-8)
        # (lambda*tan(theta)^2/4)
        # discriminant_inv is estimated using the current theta
        # If q_prev has a negative value somewhere we generate a RuntimeWarning.
        # This typically due to alpha being greater than vehicle_pitch_degrees_v at some point below
        # invert the sign here because we'll use it inverted below
        with warnings.catch_warnings():
            # RuntimeWarning: invalid value encountered in power occurs because q_prev has a negative value somewhere
            neg_i = q_prev < 0
            q_prev[neg_i] = nan
            warnings.simplefilter("ignore")
            scaled_drag = power(q_prev, -hd_s) 
        tth_v = tan(theta) # compute once
        discriminant_inv_v = hd_a2*tth_v*tth_v*scaled_drag/hd_bc4
        # NOTE: Beware when comparing this version with flightvec(2).m
        # In those version, when stalled the entries are replaced by nan rather than 0
        # Thus in matlab you need to use nanmean, etc. and here you have to be careful because of all the zeros dragging the mean down

        # valid solutions exist only for discriminant_inv > 1 (zero or complex otherwise)
        # also only consider points where flight is valid
        with warnings.catch_warnings():
            # RuntimeWarning: invalid value encountered in greater because discriminant_inv_v has a nan somewhere
            warnings.simplefilter("ignore")
            flying_i = nonzero(buoyancy_pitch_ok_v*discriminant_inv_v > 1.0)[0] 
        q[:] = 0.0 # assume the worst..stalled, no dynamic pressure or glide angle
        if len(flying_i) == 0:
            # CT reported nonsensical salinities, hence buoyancy is poor
            # deployments/CCE/labrador/sep04/sg015/p0150243
            # deployments/CCE/labrador/sep04/sg015/p0150248
            # deployments/CCE/labrador/sep04/sg015/p0150257
            # deployments/CCE/labrador/sep04/sg015/p0150263
            # deployments/CCE/labrador/oct03/sg004/p0040057

            # Probably should declare the points bad or skip this profile (suggested elsewhere)
            # but in case this hasn't happened handle things gracefully without throwing exceptions.
            log_debug("Unable to find any points where flying")
            # Report unable to converge and mark all points as stalled
            # to forestall further processing by caller
            # return umag as zero since q is zero
            return (False, q, theta, arange(num_rows)) 
        sqrt_discriminant = sqrt(1.0 - 1.0/discriminant_inv_v[flying_i])
        # Eq. 7 in the reference, obtained using the quadratic formula ...
        # q^(hd_s) considered to vary slowly compared to q (hd_s typically <= -1/4)
        # NOTE the q eqn use 1.0 + sqrt and the alpha eqn must use 1.0 - sqrt
        q[flying_i] = (buoyancy_force_v[flying_i]*sin(theta[flying_i])*scaled_drag[flying_i])/(l2_hd_b2)*(1.0 + sqrt_discriminant)
        # Eq. 8 in the reference, with critical minus sign
        # hd_a is 1/deg; hd_c is 1/deg^2 so overall alpha is in degrees
        alpha = (-hd_a*tth_v[flying_i]/hd_c2)*(1.0 - sqrt_discriminant) # degrees
        theta[:] = 0.0 # assume the worst..stalled # == math.radians(0.0)
        # defn: pitch  = glide + attack angles
        # glideangle is the difference between pitch and angle of attack (both in degrees)
        theta[flying_i] = radians(vehicle_pitch_degrees_v[flying_i] - alpha)
        max_residual = max(fabs((q[flying_i] - q_prev[flying_i])/q[flying_i]))

        # trace_array('q_%d' % j, q)
        # trace_array('th_%d' % j, theta)
        # trace_array('param_inv_%d' % j, discriminant_inv_v)

        log_debug("Hydro iteration %d max residual %f" % (j, max_residual))
        if max_residual < residual_test and j >= 2: # ensure at least 2 iterations
            converged = True;
            break   # break out of j loop 
    # end of j loop

    # compute total estimated speed through the water (rename from u_mag (which is confusing with U in the paper) to total_speed_cm_s)
    # defn: q = rho0/2*(U^2 + W^2) = rho0/2*total_speed^2
    u_mag =  m2cm*sqrt(2.0*q/rho0)
    # trace_array('umag', u_mag)
    # trace_array('theta', theta) # radians
    
    # NOTE flightvec_new.m and glide.m have code that looks for places where the final calc indicates a stall (theta  == 0)
    # and linearly interpolates a glide angle from the surrounding points (see sophisticated interpotation in flightvec_new.m)
    # and then interpolates q similarly (but could be at different points) after which u_mag would be be calculated

    # Determine other stalls...
    stalled_i_v = find_stalled(u_mag, vehicle_pitch_degrees_v, num_rows, calib_consts)
    buoyancy_pitch_stalled_i_v = where(array(buoyancy_pitch_ok_v) == 0.0)[0]
    buoyancy_pitch_stalled_i_v = buoyancy_pitch_stalled_i_v.tolist()
    if (len(buoyancy_pitch_stalled_i_v)):
        log_debug('Adding %d stalled points where pitch is opposite buoyancy forcing' % len(buoyancy_pitch_stalled_i_v))
        stalled_i_v.extend(buoyancy_pitch_stalled_i_v)
        stalled_i_v = Utils.sort_i(Utils.unique(stalled_i_v))
    u_mag[stalled_i_v] = 0.0 # assume stalled (hydro model on the verge of complex soln)
    theta[stalled_i_v] = 0.0 # going nowhere... (not NaN, which leads to bad component velocities and interpolations)
    # Ensure numpy arrays
    u_mag = array(u_mag)
    theta = array(theta)
    return (converged, u_mag, theta, stalled_i_v)


