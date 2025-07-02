import os
import threading
import time
import struct
import sys
import select
import pty
import fcntl
import atexit

# Fixed directory for virtual ports
VIRTUAL_JOYSTICK_DIR = '/tmp/virtual_joysticks'
LEFT_JOYSTICK_PATH = os.path.join(VIRTUAL_JOYSTICK_DIR, 'ttyACM0')
RIGHT_JOYSTICK_PATH = os.path.join(VIRTUAL_JOYSTICK_DIR, 'ttyACM1')

def cleanup():
    """Clean up virtual ports and directory on exit"""
    try:
        if os.path.exists(LEFT_JOYSTICK_PATH):
            os.unlink(LEFT_JOYSTICK_PATH)
        if os.path.exists(RIGHT_JOYSTICK_PATH):
            os.unlink(RIGHT_JOYSTICK_PATH)
        if os.path.exists(VIRTUAL_JOYSTICK_DIR):
            os.rmdir(VIRTUAL_JOYSTICK_DIR)
        print("Cleaned up virtual joystick ports")
    except Exception as e:
        print(f"Cleanup error: {e}")

# Register cleanup function
atexit.register(cleanup)

# Create fixed directory for virtual ports
if not os.path.exists(VIRTUAL_JOYSTICK_DIR):
    os.makedirs(VIRTUAL_JOYSTICK_DIR)
else:
    # Clean up any existing symlinks
    cleanup()
    os.makedirs(VIRTUAL_JOYSTICK_DIR)

# Create virtual serial ports
left_master, left_slave = pty.openpty()
right_master, right_slave = pty.openpty()

# Create fixed symlinks to virtual ports
left_slave_name = os.ttyname(left_slave)
right_slave_name = os.ttyname(right_slave)

os.symlink(left_slave_name, LEFT_JOYSTICK_PATH)
os.symlink(right_slave_name, RIGHT_JOYSTICK_PATH)

print(f"Virtual joysticks created at fixed paths:")
print(f"  Left joystick: {LEFT_JOYSTICK_PATH}")
print(f" Right joystick: {RIGHT_JOYSTICK_PATH}")

# Joystick state structure (matches expected protocol)
class JoystickState:
    def __init__(self):
        self.lx = 0.0
        self.ly = 0.0
        self.rx = 0.0
        self.ry = 0.0
        self.run_loco_signal = False
        self.run_squat_signal = False
        self.stopgait_signal = False
        self.start_signal = False
        self.run_signal = False
        self.left_hand_grasp_state = False
        self.right_hand_grasp_state = False
        self.damping_signal = False

    def pack(self):
        return struct.pack('ffff????????', 
                          self.lx, self.ly, self.rx, self.ry,
                          self.run_loco_signal, self.run_squat_signal,
                          self.stopgait_signal, self.start_signal,
                          self.run_signal, self.left_hand_grasp_state,
                          self.right_hand_grasp_state, self.damping_signal)

# Keyboard to Joystick Mapping
KEY_MAPPING = {
    # Left Joystick
    'w': ('left', 'ly', 1.0),
    's': ('left', 'ly', -1.0),
    'a': ('left', 'lx', -1.0),
    'd': ('left', 'lx', 1.0),
    
    # Right Joystick
    'i': ('right', 'ry', 1.0),
    'k': ('right', 'ry', -1.0),
    'j': ('right', 'rx', -1.0),
    'l': ('right', 'rx', 1.0),
    
    # Buttons
    '1': ('left', 'run_loco_signal', True),
    '2': ('right', 'run_squat_signal', True),
    '3': ('right', 'stopgait_signal', True),
    '4': ('right', 'start_signal', True),
    '5': ('right', 'run_signal', True),
    '6': ('left', 'left_hand_grasp_state', True),
    '7': ('right', 'right_hand_grasp_state', True),
    '8': ('right', 'damping_signal', True),
    
    # Reset analog sticks
    'r': ('reset', None, None),
}

# Create and initialize joystick states
left_joystick = JoystickState()
right_joystick = JoystickState()

# Set non-blocking mode
for fd in [left_master, right_master]:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def keyboard_listener():
    """Capture keyboard input and update joystick states"""
    print("\nKeyboard controls:")
    print("----------------------------------------------")
    print("Left Stick: W/S (forward/back), A/D (left/right)")
    print("Right Stick: I/K (forward/back), J/L (left/right)")
    print("Buttons:")
    print("  1: Run Locomotion Signal")
    print("  2: Run Squat Signal")
    print("  3: Stop Gait Signal")
    print("  4: Start Signal")
    print("  5: Run Signal")
    print("  6: Left Hand Grasp")
    print("  7: Right Hand Grasp")
    print("  8: Damping Signal")
    print("  R: Reset analog sticks")
    print("  Q: Quit program")
    print("----------------------------------------------")
    
    while True:
        # Use select to check for input without blocking
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if rlist:
            key = sys.stdin.read(1).lower()
            if key == 'q':
                print("\nExiting...")
                cleanup()
                os._exit(0)
                
            if key in KEY_MAPPING:
                device, attr, value = KEY_MAPPING[key]
                
                if device == 'reset':
                    # Reset analog sticks
                    left_joystick.lx = 0.0
                    left_joystick.ly = 0.0
                    right_joystick.rx = 0.0
                    right_joystick.ry = 0.0
                    print("Analog sticks reset to center")
                else:
                    joystick = left_joystick if device == 'left' else right_joystick
                    
                    # Handle special case for analog sticks
                    if attr in ['lx', 'ly', 'rx', 'ry']:
                        current_val = getattr(joystick, attr)
                        new_val = current_val + value
                        # Keep values in [-1, 1] range
                        setattr(joystick, attr, max(-1.0, min(1.0, new_val)))
                    else:
                        setattr(joystick, attr, value)
                        print(f"{device.upper()} {attr} = {value}")

def joystick_emulator():
    """Continuously write joystick states to virtual ports"""
    try:
        while True:
            # Write left joystick state
            os.write(left_master, left_joystick.pack())
            
            # Write right joystick state
            os.write(right_master, right_joystick.pack())
            
            # Reset button states after sending
            left_joystick.run_loco_signal = False
            right_joystick.run_squat_signal = False
            right_joystick.stopgait_signal = False
            right_joystick.start_signal = False
            right_joystick.run_signal = False
            right_joystick.damping_signal = False
            
            time.sleep(0.02)  # ~50Hz update rate
    except Exception as e:
        print(f"Emulator error: {e}")

if __name__ == "__main__":
    print("Starting virtual joystick emulator...")
    
    # Start threads
    threading.Thread(target=keyboard_listener, daemon=True).start()
    threading.Thread(target=joystick_emulator, daemon=True).start()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")
        cleanup()
        os.close(left_master)
        os.close(right_master)
        sys.exit(0)
