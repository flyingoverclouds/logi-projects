
import numpy

from path_tracking_service import PurePursuit as TrackingService
from state_estimate_service import RobotState
from ugv_platform import UgvPlatform as Robot
from coordinates import  *
from waypoint_provider import PlannerWayPointProvider as WayPointProvider


from gps_service import GpsService
from speed_service import SpeedService

import math

CONTROL_RATE = 50 # rate at which the control is run
TRACKER_RATE = 1 # rate at which the path tracking algorithm is run
MAX_SPEED_MS = 10.0 # 10m/s is max speed (36km/h), this parameter must be adjusted depending on required agressivity
WHEEL_BASE = 0.30 # distance between front and rear axle
DT = 1/CONTROL_RATE
DIST_TOLERANCE = 2.0



#compute the speed based on current steering. This will need to be adjusted to avoid drifting
def speedFromSteering(steering):
	speed = MAX_SPEED_MS * cos(steering) # need to adjusted ... 
	return speed
		

def populateSensorMap(robot, gps_service):
	pos = robot.getPosition()
	sensor_map = {}
	sensor_map[Controller.imu_key] = (1, robot.getEuler(), robot.getGyro())
	sensor_map[Controller.gps_key] = pos
	sensor_map[Controller.speed] = pos
	return sensor_map
	

def nav_loop():
	robot = Robot()
	state = RobotState()
	path_tracker = TrackingService()
	wp = WayPointProvider() # use whatever WaypointProvider
	

	mpu_valid = -1
	print "waiting for GPS fix"
	gps_service = GpsService()
	current_pos = gps_service.getPosition()
	# wainting to get a valid GPS fix. Maybe should also wait to get a good fix before starting
	while not current_pos.valid:
		time.sleep(1)
		current_pos = gps_service.getPosition()
	#initializing local coordinates system to start on current spot
	coordinates_system = LocalCoordinates(current_pos)
	old_gps = current_pos
	
	#initiliaze mpu system
	while mpu_valid < 0:
		time.sleep(0.5)
		mpu_valid = mpu9150.mpuInit(1, CONTROL_RATE, 4)
	print mpu_valid
	
	#setting mpu calibration files (calibration should be re-run before every run)
	mpu9150.setMagCal('./magcal.txt')
	mpu9150.setAccCal('./accelcal.txt')
	for i in range(1000): # flushing a bit of sensor fifo to stabilize sensor
		time.sleep(1/CONTROL_RATE)
		mpu9150.mpuRead()

	#initializing actuators and failsafe
	robot.setSteeringAngle(0.0)
	robot.setSpeed(0)
	robot.setSpeedFailsafe(0)
	robot.setSteeringFailsafe(0.0)
	
	while True:
		#reseting watchdog at the beginning of loop
		robot.resetWatchdog()
		
		#waypoint service provide the current waypoint
		target_pos= wp.getCurrentWayPoint()
		
	
		#no target point means path is done
		if target_pos == None: # done with the path
			break
		xy_target_pos = coordinates_system.convertGpstoEuclidian(target_pos)
		#get previous waypoint to draw the path between the two
		origin_pos = wp.getPreviousWaypoint()
		xy_origin_pos = coordinates_system.convertGpstoEuclidian(origin_pos)

		# populate the sensor structure to make sure we read all sensors only once per loop
		sensors = populateSensorMap(robot, gps_service)
		
		#imu has no valid sample, IMU helps keep the control loop rate as it delivers values at the right pace
		if sensor[IController.imu_key][0] < 0 : #invalid imu sample, wait a bit to read next
			time.sleep(0.01)
			continue
		
		#converting gps pos to the local coordinates system
		xy_pos = coordinates_system.convertGpstoEuclidian(sensors[Controller.gps_key])
		new_gps_fix = sensors[Controller.gps_key].time != old_gps.time
		old_gps = sensors[Controller.gps_key]
		
		# we have a new fix, integrate it to the kalman filter
		robot_heading = sensor[IController.imu_key][1][2]		
		if new_gps_fix :
			robot_state = state_estimate_service.computeEKF(robot_heading, sensor[IController.odometry_key], xy_pos.x, xy_pos.y, DT)
		else:
			robot_state = state_estimate_service.computeEKF(robot_heading, sensor[IController.odometry_key], None, None, DT)
		
		# updating xy_pos to estimated pos
		xy_pos = EuclidianPoint(robot_state[0], robot_state[1], xy_pos.time, True)
		robot_heading = robot_state[2]
		# execute tracker at a fraction at the control rate update
		if tracker_counter >= (CONTROL_RATE/TRACKER_RATE):
			path_curvature = path_tracker.computeSteering(xy_origin_pos, xy_target_pos, xy_pos, robot_heading)
			tracker_counter = 0
		else:
			tracker_counter = tracker_counter + 1	
				
		#steering can be extracted from curvature while speed must be computed from curvature and max_speed
		steering = sinh(WHEEL_BASE * path_curvature) 
		#command needs to be computed for speed using PID control or direct P control
		speed = speedFromSteering(steering))	
		robot.setSpeed(speed)
		robot.setSteeringAngle(steering)

		# if we reached target, move to the next
		if xy_pos.distanceTo(xy_target_pos) < DIST_TOLERANCE:
			wp.getNextWayPoint()
			# for tracker to be executed on next iteration
			tracker_counter = (CONTROL_RATE/TRACKER_RATE)
					
	
	# if ever we quit the loop, we need to set the speed to 0 and steering to 0
	robot.setSteeringAngle(0.0)        
	robot.setSpeed(0)
	print "Shutdown ESC then quit programm (for safety reason)"
        while True:
		time.sleep(1)	

if __name__ == "__main__":
	try:
		nav_loop()
	except KeyboardInterrupt:
		print "dying !"
		exit()