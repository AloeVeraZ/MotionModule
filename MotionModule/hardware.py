"""MotionModule hardware definitions.

Keep this file next to robot.py to customize that robot.
Use module.motor("name").set(0.25) or module.servo("name").set_angle(90).
forward_gpio and reverse_gpio are BCM GPIO numbers, not physical header pins.
Motor inversion changes direction without changing the wiring.
Servo board is the index in addresses; channel is the board output (0-15).
Edit plain values only; this file is read without executing Python code.
See Debug > Wiring in the dashboard for physical connections and driver labels.
"""

HARDWARE = {'module': {'pwm_hz': 1000, 'deadtime_ms': 15, 'watchdog_ms': 500},
 'motors': {1: {'name': 'driver_1a', 'forward_gpio': 26, 'reverse_gpio': 19, 'inverted': True},
            2: {'name': 'driver_1b', 'forward_gpio': 13, 'reverse_gpio': 6, 'inverted': False},
            3: {'name': 'driver_2a', 'forward_gpio': 21, 'reverse_gpio': 20, 'inverted': True},
            4: {'name': 'driver_2b', 'forward_gpio': 16, 'reverse_gpio': 12, 'inverted': False},
            5: {'name': 'driver_3a', 'forward_gpio': 11, 'reverse_gpio': 9, 'inverted': True},
            6: {'name': 'driver_3b', 'forward_gpio': 7, 'reverse_gpio': 8, 'inverted': False},
            7: {'name': 'driver_4a', 'forward_gpio': 22, 'reverse_gpio': 27, 'inverted': True},
            8: {'name': 'driver_4b', 'forward_gpio': 24, 'reverse_gpio': 23, 'inverted': False}},
 'servos': {'enabled': True,
            'i2c_bus': 1,
            'frequency_hz': 50,
            'addresses': [64],
            'minimum_pulse_us': 500,
            'maximum_pulse_us': 2500,
            'output_enable_gpio': 4,
            'channels': {0: {'name': 'servo_0', 'board': 0, 'channel': 0},
                         1: {'name': 'servo_1', 'board': 0, 'channel': 1},
                         2: {'name': 'servo_2', 'board': 0, 'channel': 2},
                         3: {'name': 'servo_3', 'board': 0, 'channel': 3},
                         4: {'name': 'servo_4', 'board': 0, 'channel': 4},
                         5: {'name': 'servo_5', 'board': 0, 'channel': 5},
                         6: {'name': 'servo_6', 'board': 0, 'channel': 6},
                         7: {'name': 'servo_7', 'board': 0, 'channel': 7},
                         8: {'name': 'servo_8', 'board': 0, 'channel': 8},
                         9: {'name': 'servo_9', 'board': 0, 'channel': 9},
                         10: {'name': 'servo_10', 'board': 0, 'channel': 10},
                         11: {'name': 'servo_11', 'board': 0, 'channel': 11},
                         12: {'name': 'servo_12', 'board': 0, 'channel': 12},
                         13: {'name': 'servo_13', 'board': 0, 'channel': 13},
                         14: {'name': 'servo_14', 'board': 0, 'channel': 14},
                         15: {'name': 'servo_15', 'board': 0, 'channel': 15}}}}
