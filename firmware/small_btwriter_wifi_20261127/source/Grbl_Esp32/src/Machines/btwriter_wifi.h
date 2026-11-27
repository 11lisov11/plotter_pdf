#pragma once

// Recovered from the ORIGINAL controller's startup diagnostics, 2026-11-27.
// This is the SMALL BtWriter, base MAC A4:F0:0F:75:C5:0C.
// Keep Cartesian standard steppers, including Z (NOT an RC servo).
#define MACHINE_NAME "BtWriter"
#define N_AXIS 3

#define X_STEP_PIN GPIO_NUM_33
#define X_DIRECTION_PIN GPIO_NUM_32
#define Y_STEP_PIN GPIO_NUM_27
#define Y_DIRECTION_PIN GPIO_NUM_26
#define Z_STEP_PIN GPIO_NUM_14
#define Z_DIRECTION_PIN GPIO_NUM_12
#define STEPPERS_DISABLE_PIN GPIO_NUM_25

#define X_LIMIT_PIN GPIO_NUM_35
#define Y_LIMIT_PIN GPIO_NUM_34

#define SPINDLE_TYPE SpindleType::LASER
#define SPINDLE_OUTPUT_PIN GPIO_NUM_4
#define COOLANT_FLOOD_PIN GPIO_NUM_21
#define COOLANT_MIST_PIN GPIO_NUM_22

// No probe, Z limit, safety-door inputs, CoreXY, or servo conversion.
// Match the factory controller's $S snapshot even when NVS uses defaults.
#define DEFAULT_X_STEPS_PER_MM 80.0
#define DEFAULT_Y_STEPS_PER_MM 80.0
#define DEFAULT_Z_STEPS_PER_MM 100.0
#define DEFAULT_X_MAX_RATE 5000.0
#define DEFAULT_Y_MAX_RATE 5000.0
#define DEFAULT_Z_MAX_RATE 8000.0
#define DEFAULT_X_ACCELERATION 3000.0
#define DEFAULT_Y_ACCELERATION 3000.0
#define DEFAULT_Z_ACCELERATION 8000.0
#define DEFAULT_X_HOMING_MPOS -0.100
#define DEFAULT_Y_HOMING_MPOS -0.100
#define DEFAULT_Z_HOMING_MPOS -0.100
#define DEFAULT_DIRECTION_INVERT_MASK 7
#define DEFAULT_HOMING_DIR_MASK 7
#define DEFAULT_HOMING_CYCLE_0 bit(X_AXIS)
#define DEFAULT_HOMING_CYCLE_1 bit(Y_AXIS)
#define DEFAULT_SPINDLE_FREQ 1000.0
