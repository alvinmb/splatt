# Splatt! Target shooting training system

# References:
#   https://www.pyimagesearch.com/2014/09/29/finding-brightest-spot-image-using-python-opencv/
#   https://github.com/spatialaudio/python-sounddevice/issues/316
#   https://stackoverflow.com/questions/25191620/creating-lowpass-filter-in-scipy-understanding-methods-and-units

#  TODO:
#  Export of recorded data to CSV
#  Configuration (device IDs etc) - setup, store and retrieval

print('Splatt initialising...')

import numpy as np       # pip install numpy / apt install python-numpy
import cv2               # pip install opencv-python / apt install python3-opencv
import sounddevice as sd # pip install sounddevice (requires libffi-dev)
import random
from time import time

# Debug settings
debug_level =  0  # 0 (off), 1 (info), 2 (detailed)
debug_max = 2     # max debug level

# Virtual shooting range and session options
real_range_length = 5       # (units must match simulated range length)
shot_calibre = 5.6          # mm (0.22")
session_name = 'Practice 13/01/23'
auto_reset = True           # reset after shot taken
auto_reset_time = 1         # Number of seconds after the shot before resetting
target_index = 0

# Target dimensions
# (name, diameter (mm), filename, simulated_range_length)
target = (('25 yard prone', 51.39, '1989 25yard Outward Gauging.png', 25),
          ('50 yard prone', 102.79, '1989 50yard Inward Gauging.png', 50),
          ('100 yard prone', 205.55, '1989 100yard Inward Gauging.png', 100))

target_name = target[target_index][0]
target_diameter = target[target_index][1]
target_filename = target[target_index][2]
simulated_range_length = target[target_index][3]

# Scaling variables
scale_factor = simulated_range_length / real_range_length
  
# video capture object
video_capture_device = 1 # TODO: make this better
video_capture = cv2.VideoCapture(video_capture_device)
captured_image_flip_needed = True # Whether the camera is mounted upside down
video_frames = []

# Check the video stream started ok
assert video_capture.isOpened()

video_width = int(video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
video_height = int(video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
video_size = (video_width, video_height)
video_fps = int(video_capture.get(cv2.CAP_PROP_FPS))

scaled_shot_radius = int(0.5 * shot_calibre * video_height / target_diameter)

if debug_level > 0:
    print(video_width , 'x' , video_height, ' @ ', video_fps, ' fps.')

# Recording options
record_video = False # (Do not set to true here)
video_output_file = 'output.avi'
composite_output_file = 'composite.png'

# Audio and video processing options
blur_radius = 11          # must be an odd number, or else GaussianBlur will fail. Lower is better for picking out point sources
detection_threshold = 50  # Trigger value to detect the reference point
click_threshold = 50      # audio level that triggers a 'shot'

# Plotting colours and options
init_line_colour = (0, 0, 255, 0) # (Blue, Green, Red)
shot_colour = (255, 0, 255)       # Magenta
line_thickness = 2
colour_change_rate = (0, 15, -15) # Rates of colour change per frame (b, g, r)

# Initialise tuples and variables
line_colour = []
stored_trace = []
composite_shots = []
start_trace = 1
shots_fired = -1 # The 0th is the calibration shot TODO: reset on keypress
auto_reset_time_expired = False

# Coordinates of the 'fired' shot
recorded_shot_loc = []

# Calibration / scaling
calib_XY = (0, 0)

# Font details
font = cv2.FONT_HERSHEY_PLAIN
font_scale = np.ceil( scaled_shot_radius / 13 )
font_thickness = 1
line_type = 1

# Sound capture parameters
audio_chunk_size = 4096
if debug_level > 0:
    print(sd.query_devices()) # Choose device numbers from here. TODO: Get/save config / -l(ist) option

audio_stream = sd.Stream(
  device = None,
  samplerate = 44100,
  channels = 1,
  blocksize = audio_chunk_size)

# Shot tracking
shot_fired = False
first_shot = True

# Open target png  and create target_image and composite_image based on video frame size
target_file_image = cv2.imread(target_filename)

if ( target_file_image.shape[0] != target_file_image.shape[1]):
    # Target image should be square
    print('Warning: Target image is not square')

# Resize the target image to fit the video frame
target_file_image = cv2.resize(target_file_image, (video_height, video_height))

# Create a new blank target image
blank_target_image = np.zeros([video_height, video_width, 3], dtype = np.uint8)

# And colour it the same as the bottom-left (is it?) pixel of the target file
blank_target_image[:, :] = target_file_image[1:2, 1:2]

# Calculate the horizontal offset for centering the target image within the frame
target_offset = int(blank_target_image.shape[1]/2 - target_file_image.shape[1]/2)

# Copy the target file into the blank target image
blank_target_image[0:target_file_image.shape[1], target_offset:target_file_image.shape[0] + target_offset] = target_file_image

# Copy the blank target image to the two images we use for display
target_image = blank_target_image.copy()
composite_image = blank_target_image.copy()

# Start listening and check it started
audio_stream.start()
assert audio_stream.active

# Functions

def initialise_trace():
    # Clear the trace and reload target_image
    global start_trace, stored_trace, recorded_shot_loc, line_colour, shot_fired, target_image, composite_image, auto_reset_time_expired
    start_trace = 1
    stored_trace = []
    recorded_shot_loc = []
    line_colour = []
    shot_fired = False
    target_image = cv2.imread(target_filename)
    target_image = blank_target_image.copy()
    auto_reset_time_expired = False

def calibrate_offset():
    # Calibrate offset to point source
    global calib_XY
    calib_XY = (int((video_width / 2) - max_loc[0]), int((video_height / 2) - max_loc[1]))
    if debug_level > 0:
        print('Calibration offset:', calib_XY)


################################################## Main Loop ##################################################


while True:

    # Get the video frame
    video_ret, video_frame = video_capture.read()
    captured_image = video_frame.copy()

    # If set, flip the image
    if captured_image_flip_needed:
        captured_image = cv2.flip(captured_image, -1)

    # grey-ify the image
    grey_image = cv2.cvtColor(captured_image, cv2.COLOR_BGR2GRAY)

    # apply a Gaussian blur to the image then find the brightest region
    grey_image = cv2.GaussianBlur(grey_image, (blur_radius, blur_radius), 0)

    # Find the point of max brightness
    (min_brightness, max_brightness, min_loc, max_loc) = cv2.minMaxLoc(grey_image)

    if debug_level > 1:
        print(max_brightness, '@', max_loc)

    # If minimum brightness not met skip the rest of the loop
    if max_brightness > detection_threshold:

        # Check for click
        audio_data, audio_overflowed = audio_stream.read(audio_chunk_size)
        volume_norm = np.linalg.norm(audio_data[:, 0]) * 10
        
        # Offset the location based on the calibration
        max_loc_x = int(( max_loc[0] + calib_XY[0] ) )
        max_loc_y = int(( max_loc[1] + calib_XY[1] ) )

        if not first_shot:
            # Scale based on the virtual / real range distances
            max_loc_x = int( scale_factor * (max_loc_x - video_width / 2) + video_width /2 )
            max_loc_y = int( scale_factor * (max_loc_y - video_height / 2) + video_height /2 )

            # Limit the coordinates to the video frame
            if max_loc_x < 0:
                max_loc_x = 0
            elif max_loc_x > video_width:
                max_loc_x = video_width

            if max_loc_y < 0:
                max_loc_y = 0
            elif max_loc_y > video_height:
                max_loc_y = video_height

            # Store the scaled coordinates (unless it's the calibration 'shot')
            max_loc = (max_loc_x, max_loc_y)
        
        # Add the discovered point to our list with the initial line colour
        stored_trace.append((max_loc_x, max_loc_y))
        line_colour.append(init_line_colour)

    # Append the new frame
    if record_video:
        video_frames.append(target_image.copy())

    # Plot the line traces so far
    for n in range(start_trace, len(stored_trace)):
        this_line_colour = list(line_colour[n])

        if not shot_fired:

            # Check audio levels TODO: FFT analysis
            if volume_norm >= click_threshold:
                recorded_shot_loc = max_loc
                shot_fired = True
                shots_fired += 1
                shot_time = time() + auto_reset_time

            # Change the colour of the traces based on colour_change_rate[]
            for c in range (0,3):
                this_line_colour[c] = this_line_colour[c] + colour_change_rate[c]
                if this_line_colour[c] > 255:
                    this_line_colour[c] = 255
                elif this_line_colour[c] < 0:
                    this_line_colour[c] = 0
            line_colour[n] = tuple(this_line_colour)
        else:
            if time() > shot_time:
                auto_reset_time_expired = True

        # Draw a line from the previous point to this one
        cv2.line(target_image, stored_trace[n-1], stored_trace[n], line_colour[n], line_thickness)

    # Draw the shot circle if it's been taken
    if recorded_shot_loc:
        cv2.circle(target_image, recorded_shot_loc, scaled_shot_radius, shot_colour, -1)

        if not first_shot:
            composite_shots.append(recorded_shot_loc)

            composite_image = blank_target_image.copy()
            shots_plotted = 0
            for recorded_shot in composite_shots:
                shots_plotted += 1
                composite_colour = (random.randint(1, 64) * 4 - 1, random.randint(32, 64) * 4 - 1, random.randint(1, 64) * 4 - 1)
                cv2.circle(composite_image, recorded_shot, scaled_shot_radius, composite_colour, line_thickness)
                
                # Number the shot on the composite image
                text_size = cv2.getTextSize(str(shots_plotted), font, font_scale, font_thickness)[0]
                text_X = int((recorded_shot[0] - (text_size[0]) / 2))
                text_Y = int((recorded_shot[1] + (text_size[1]) / 2))

                cv2.putText(composite_image, str(shots_plotted), 
                    (text_X, text_Y),
                    font, font_scale, composite_colour, font_thickness, line_type)

            # Find the bounding circle of all shots so far
            if len(composite_shots) > 1:
                (bc_X, bc_Y), bc_radius = cv2.minEnclosingCircle(np.asarray(composite_shots))
                bc_centre = (int(bc_X), int(bc_Y))
                cv2.circle(composite_image, bc_centre, int(bc_radius + scaled_shot_radius), (0, 255, 255), 2)

                actual_spread = (2 * bc_radius * target_diameter / video_height) # (mm)
                cv2.putText(composite_image, 'Spread: ' + str(np.around(actual_spread, 2)) + 'mm', (5, 25), font, 1, (0, 0, 0), 1, 1)
            

        # Remember to do anything else required with the recorded shot location here (eg csv output)
        recorded_shot_loc = ()

        if first_shot:
            # Calibrate the system and clear the results
            calibrate_offset()
            initialise_trace()
            first_shot = False
            
    # display the results
    cv2.imshow("Splatt - Live trace", target_image)
    cv2.imshow("Splatt - Composite", composite_image)

    if debug_level > 0:
        cv2.imshow("Splatt - Grey", grey_image)

    if auto_reset_time_expired:
        initialise_trace()

    # Check for user input
    key_press = cv2.waitKey(1) & 0xFF
    
    if key_press == ord('q'):
        # Quit
        video_capture.release()
        audio_stream.close()
        # TODO: close video file if open as well?
        break

    elif key_press == ord('c'):
        # Clear the trace
        initialise_trace()
    
    elif key_press == ord('v'):
        # Start recording
        if not record_video:
            video_start_time = time()
            video_frames = []
            record_video = True
            print('Recording started')
        else:
            # Save the video
            # Define the codec and create VideoWriter object
            video_length = time() - video_start_time
            video_fps = int(len(video_frames) / video_length)
            four_cc = cv2.VideoWriter_fourcc(*'XVID')
            video_out = cv2.VideoWriter(video_output_file, four_cc, video_fps, video_size)

            for frame in video_frames:
                video_out.write(frame)

            record_video = False
            print('Recording saved as:', video_output_file)
    
    elif key_press == ord('d'):
        # Increase debug level
        debug_level += 1
        if debug_level > debug_max:
            debug_level = False
        print('Debug level:', int(debug_level))
    
    elif key_press == ord('r'):
        # Reset for recalibration
        first_shot = True

    elif key_press == ord('s'):
        # Save the composite image (and clear it?)
        cv2.imwrite(composite_output_file, composite_image)
    
    elif key_press == ord('f'):
        # Change the flip mode
        captured_image_flip_needed = not captured_image_flip_needed
        print('Flip required:', captured_image_flip_needed)
