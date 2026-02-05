import RPi.GPIO as GPIO
from time import sleep
import time
from rpi_ws281x import PixelStrip, Color
import threading
import random
import colorsys
import math
import datetime

# V15 PROD VERSION
# Has all fixes 
# 

#### GLOBAL STATE ####
heartBeat_bpm = 0        
is_recovering = False
last_input_time = time.time()
current_decay_delay = 20 

# --- GLOBAL TIMER & BURN STATE ---
burn_mode_active = False
BURN_START_TIME = datetime.datetime(2026, 2, 8, 7, 0, 0) # Sunday at 7 AM GMT (1AM MT)

# --- GLOBAL IDLE & DANCE STATE ---
idle_start_time = None
dance_triggered = False 
dance_is_running = False  
IDLE_DANCE_TIMEOUT = 10.0
IDLE_JITTER_MAX = 30.0
DANCE_DURATION = 35.0 
current_idle_goal = IDLE_DANCE_TIMEOUT + random.uniform(0, IDLE_JITTER_MAX)

# --- STAGE ORDER CONFIGURATION ---
STAGE_ORDERS = [1, 2, 3]

# --- GLOBAL ROUND/LEVEL SETTINGS ---
ROUNDS_PER_LEVEL = 2 
STAGE_1_LEVELS = [3, 4, 5]
STAGE_2_LEVELS = [5, 6, 7]
STAGE_3_LEVELS = [3, 4, 5] 

# --- GLOBAL TIMING SETTINGS ---
LEVEL_DISPLAY_TIME = 0.5       
LEVEL_BLINK_GAP = 0.3          
STAGE_3_SPEED_MULTIPLIER = 0.30 
INVITE_BLINK_DURATION = 0.4    
INVITE_BLINK_GAP = 0.3         

# Pacing & Cooldowns
POST_WIN_DANCE_PAUSE = 3.5     
POST_INDICATOR_DELAY = 2.0      
POST_INPUT_DELAY = 1.0      

# --- GLOBAL BRIGHTNESS REGISTRY ---
GAME_INVITE_BRIGHTNESS = 30    
GAME_PLAY_BRIGHTNESS = 50      
GAME_FEEDBACK_BRIGHTNESS = 20  
GAME_INDICATOR_BRIGHTNESS = 20 
WIN_DANCE_BRIGHTNESS = 60      
FINAL_VICTORY_BRIGHTNESS = 80  
IDLE_DANCE_BRIGHTNESS = 80     
HIBERNATION_BRIGHTNESS = 60     
PULSE_PEAK_BRIGHTNESS = 90     
PULSE_LOW_BRIGHTNESS = 20       
OFF_PULSE_BRIGHTNESS = 0        

# --- GAME SETTINGS ---
game_active = False
GAME_TRIGGER_LEN = 3        
GAME_PRESS_TIMEOUT = 2.0    
GAME_ENTRY_WINDOW = 6.0    
TRIGGER_ENTRY_WINDOW = 30.0 
GAME_WIN_DANCE_DURATION = 5.0
INVITE_DELAY_BASE = 3.0   # Minimum seconds to wait after dance ends
INVITE_DELAY_JITTER = 10.0 # Maximum random extra seconds to add to the delay

# --- SECRET CODE PARAMETERS ---
STOP_DURATION = 1.0      
is_stopping = False      
current_sequence = []
secret_code_hibernation = [17, 17, 22, 17]
secret_code_game = [17, 22, 22, 17]            
SECRET_TIMEOUT = 5.0  
last_secret_press_time = 0
button_lock = threading.Lock()
led_lock = threading.Lock() 

# --- MOTOR BPM TUNING PARAMETERS --- 
INITIAL_START_BPM = 30  
BPM_INCREMENT_FAST = 10 
BPM_INCREMENT_SLOW = 10 
BURN_BPM_INCREMENT = 5 
DECAY_STEP = 5 
DECAY_TICK_RATE = 0.5 
MOTOR_PULSE_DURATION = 0.450 
MOTOR_MAX_BPM = 75 
MOTOR_MIN_BPM = 10  

# --- HOLD PARAMETERS ---
HOLD_BPM_CHANGE = 5 
SLOW_HOLD_THRESHOLD = 1.6 

# --- HEARTBEAT RHYTHM TUNING ---
LUB_DURATION_PCT = 0.15     # % of total beat time for first pulse
DUB_DURATION_PCT = 0.10     # % of total beat time for second pulse
INTERNAL_GAP_PCT = 0.05     # % of total beat time between Lub and Dub
DUB_BRIGHTNESS_RATIO = 0.7  # Intensity of second pulse (0.7 = 70% of peak)

# --- DUAL HOLD COLOR CYCLE ---
dual_hold_active = False
cycle_hue = random.random()
CYCLE_SPEED = 1.0 / 10.0  # Full rotation (1.0) over 30 seconds


#### SETUP HARDWARE ####
in1, in2, en = 23, 24, 25
BUTTON_FAST, BUTTON_SLOW = 17, 22 

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in [in1, in2, en]: 
    GPIO.setup(pin, GPIO.OUT)
GPIO.setup(BUTTON_FAST, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(BUTTON_SLOW, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

p = GPIO.PWM(en, 100)
p.start(0)

LED_COUNT, LED_PIN = 30, 18
strip = PixelStrip(LED_COUNT, LED_PIN, 800000, 10, False, 255, 0)
strip.begin()

def debug_log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")

#### VISUAL FUNCTIONS ####
def set_all_leds(color, brightness=None):
    with led_lock:
        if brightness is not None: strip.setBrightness(brightness)
        for i in range(LED_COUNT): strip.setPixelColor(i, color)
        strip.show()

def game_win_dance(is_final=False):
    brightness = FINAL_VICTORY_BRIGHTNESS if is_final else WIN_DANCE_BRIGHTNESS
    green_hues = [0.28, 0.3, 0.33, 0.35, 0.4] 
    other_hues = [0.1, 0.6, 0.8] 
    start = time.time()
    while time.time() - start < GAME_WIN_DANCE_DURATION:
        for i in range(LED_COUNT):
            with led_lock:
                strip.setBrightness(brightness)
                selected_hue = random.choices([random.choice(green_hues), random.choice(other_hues)], weights=[80, 20])[0]
                rgb = colorsys.hls_to_rgb(selected_hue, 0.5, 1.0)
                strip.setPixelColor(i, Color(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255)))
                strip.show()
            time.sleep(0.05)
    set_all_leds(Color(0,0,0), OFF_PULSE_BRIGHTNESS)
    time.sleep(POST_WIN_DANCE_PAUSE)

def game_lose_visual():
    for _ in range(5):
        set_all_leds(Color(0, 255, 0), GAME_INDICATOR_BRIGHTNESS)
        time.sleep(0.3); set_all_leds(Color(0, 0, 0), OFF_PULSE_BRIGHTNESS); time.sleep(0.3)

def dance_visual():
    global dance_is_running, dance_triggered, idle_start_time, current_idle_goal
    if burn_mode_active: return 
    dance_is_running = True
    start_dance = time.time()
    hue_base = random.random()
    
    while True:
        elapsed = time.time() - start_dance
        if elapsed > DANCE_DURATION or heartBeat_bpm > 0 or game_active: 
            break
            
        fade_val = math.sin((elapsed / DANCE_DURATION) * math.pi) * 0.4
        with led_lock:
            strip.setBrightness(IDLE_DANCE_BRIGHTNESS)
            hue_base = (hue_base + 0.007) % 1.0 
            for i in range(LED_COUNT):
                pixel_hue = (hue_base + (i * 0.04)) % 1.0
                rgb = colorsys.hls_to_rgb(pixel_hue, 0.5, 1.0)
                strip.setPixelColor(i, Color(int(rgb[0]*255*fade_val), int(rgb[1]*255*fade_val), int(rgb[2]*255*fade_val)))
            strip.show()
        time.sleep(0.04)
        
    set_all_leds(Color(0,0,0), OFF_PULSE_BRIGHTNESS)
    dance_is_running = False
    
    # Trigger game progression after a randomized delay
    if heartBeat_bpm == 0 and not game_active:
        # Calculate the random gap
        total_delay = INVITE_DELAY_BASE + random.uniform(0, INVITE_DELAY_JITTER)
        debug_log(f"[IDLE] Dance ended. Waiting {total_delay:.2f}s before invite.")
        
        # Non-blocking wait: check if a button is pressed during this gap
        gap_start = time.time()
        while time.time() - gap_start < total_delay:
            if heartBeat_bpm > 0 or game_active: # User pressed a button or secret code
                return
            time.sleep(0.1)

        run_full_game_progression()
        dance_triggered = False
        idle_start_time = time.time()
        current_idle_goal = IDLE_DANCE_TIMEOUT + random.uniform(0, IDLE_JITTER_MAX)


def hibernation_visual():
    pixel_hues = [random.random() for _ in range(LED_COUNT)]
    while is_recovering:
        with led_lock:
            strip.setBrightness(HIBERNATION_BRIGHTNESS)
            for i in range(LED_COUNT):
                pixel_hues[i] = (pixel_hues[i]) % 1.0
                rgb = colorsys.hls_to_rgb(pixel_hues[i], 0.6, 0.8) 
                strip.setPixelColor(i, Color(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255)))
            strip.show()
        time.sleep(0.04)
    set_all_leds(Color(0,0,0), OFF_PULSE_BRIGHTNESS)

#### MOTOR HELPERS ####
def trigger_motor_pulse():
    # PHANTOM PULSE FIX: Motor is gated by BPM value
    if heartBeat_bpm <= 0:
        return
    GPIO.output(in1, GPIO.HIGH); GPIO.output(in2, GPIO.LOW); p.ChangeDutyCycle(100)
    time.sleep(MOTOR_PULSE_DURATION); p.ChangeDutyCycle(0)

#### GAME LOGIC ####
def play_sequence(sequence, brightness, duration, gap):
    for pin in sequence:
        color = Color(255, 0, 0) if pin == BUTTON_FAST else Color(0, 255, 0)
        set_all_leds(color, brightness)
        time.sleep(duration); set_all_leds(Color(0, 0, 0), OFF_PULSE_BRIGHTNESS); time.sleep(gap)

def capture_input(length, timeout, pulse_motor=False):
    user_seq = []
    start_time = time.time(); last_press_time = time.time()
    while len(user_seq) < length:
        if (time.time() - start_time) > timeout: return user_seq if user_seq else None 
        if len(user_seq) > 0 and (time.time() - last_press_time) > GAME_PRESS_TIMEOUT: return user_seq
        button_hit = None
        if GPIO.input(BUTTON_FAST) == GPIO.HIGH: button_hit = BUTTON_FAST
        elif GPIO.input(BUTTON_SLOW) == GPIO.HIGH: button_hit = BUTTON_SLOW
        if button_hit:
            user_seq.append(button_hit)
            if pulse_motor: threading.Thread(target=trigger_motor_pulse, daemon=True).start()
            set_all_leds(Color(255, 0, 0) if button_hit == BUTTON_FAST else Color(0, 255, 0), GAME_FEEDBACK_BRIGHTNESS)
            while GPIO.input(button_hit) == GPIO.HIGH: time.sleep(0.05)
            set_all_leds(Color(0, 0, 0), OFF_PULSE_BRIGHTNESS); last_press_time = time.time()
        time.sleep(0.05)
    time.sleep(POST_INPUT_DELAY); return user_seq

def run_stage(stage_id):
    stages_config = {1: {"levels": STAGE_1_LEVELS, "speed": 1.0}, 2: {"levels": STAGE_2_LEVELS, "speed": 1.0}, 3: {"levels": STAGE_3_LEVELS, "speed": STAGE_3_SPEED_MULTIPLIER}}
    config = stages_config.get(stage_id)
    if not config: return True
    for l_idx, seq_len in enumerate(config['levels']):
        wins = 0
        while wins < ROUNDS_PER_LEVEL:
            passed = False
            for attempt in range(3):
                seq = [random.choice([BUTTON_FAST, BUTTON_SLOW]) for _ in range(seq_len)]
                play_sequence(seq, GAME_PLAY_BRIGHTNESS, LEVEL_DISPLAY_TIME * config['speed'], LEVEL_BLINK_GAP * config['speed'])
                entry = capture_input(seq_len, GAME_ENTRY_WINDOW)
                if entry == seq:
                    set_all_leds(Color(255, 0, 0), GAME_INDICATOR_BRIGHTNESS); time.sleep(0.5)
                    set_all_leds(Color(0,0,0), OFF_PULSE_BRIGHTNESS); wins += 1; passed = True; time.sleep(POST_INDICATOR_DELAY)
                    break
                else:
                    set_all_leds(Color(0, 255, 0), GAME_INDICATOR_BRIGHTNESS); time.sleep(0.5)
                    set_all_leds(Color(0,0,0), OFF_PULSE_BRIGHTNESS); time.sleep(POST_INDICATOR_DELAY)
            if not passed: return False
    return True

def run_full_game_progression():
    global game_active, heartBeat_bpm, last_input_time
    game_active = True
    heartBeat_bpm = 0 # Silent during invite lights
    
    t_seq = [random.choice([BUTTON_FAST, BUTTON_SLOW]) for _ in range(GAME_TRIGGER_LEN)]
    play_sequence(t_seq, GAME_INVITE_BRIGHTNESS, INVITE_BLINK_DURATION, INVITE_BLINK_GAP)
    
    entry = capture_input(GAME_TRIGGER_LEN, TRIGGER_ENTRY_WINDOW, pulse_motor=True)
    
    if entry != t_seq:
        heartBeat_bpm = INITIAL_START_BPM if (entry is not None and BUTTON_FAST in entry) else 0
        game_active = False; last_input_time = time.time(); return

    # Sequence matched: Start heartbeat and stages
    heartBeat_bpm = INITIAL_START_BPM 
    for stage_id in STAGE_ORDERS:
        if run_stage(stage_id): game_win_dance(is_final=(stage_id == STAGE_ORDERS[-1]))
        else: game_lose_visual(); break
        
    game_active = False; heartBeat_bpm = 0; last_input_time = time.time()

#### ENGINE FUNCTIONS ####
def heartBeat_led_pulse(speed):
    if speed < 1 or is_recovering or dance_is_running or game_active: 
        return
    
    # Calculate current color: Default Green or Cycle Hue
    with led_lock:
        if dual_hold_active:
            rgb = colorsys.hls_to_rgb(cycle_hue, 0.5, 1.0)
            current_color = Color(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
        else:
            current_color = Color(0, 255, 0) # Standard Green
            
        for i in range(LED_COUNT): 
            strip.setPixelColor(i, current_color) 
    
    spb = 60.0 / max(speed, MOTOR_MIN_BPM)

    def run_sub_pulse(target_b, duration):
        steps = 8
        step_sleep = (duration / 2) / steps
        for b in range(PULSE_LOW_BRIGHTNESS, target_b + 1, max(1, (target_b - PULSE_LOW_BRIGHTNESS) // steps)):
            if heartBeat_bpm < 1 or dance_is_running or game_active: return
            with led_lock: strip.setBrightness(b); strip.show()
            time.sleep(step_sleep)
        for b in range(target_b, PULSE_LOW_BRIGHTNESS - 1, -max(1, (target_b - PULSE_LOW_BRIGHTNESS) // steps)):
            if heartBeat_bpm < 1 or dance_is_running or game_active: return
            with led_lock: strip.setBrightness(b); strip.show()
            time.sleep(step_sleep)

    # 1. First Pulse (Lub)
    run_sub_pulse(PULSE_PEAK_BRIGHTNESS, spb * LUB_DURATION_PCT)
    # 2. Internal Gap
    time.sleep(spb * INTERNAL_GAP_PCT)
    # 3. Second Pulse (Dub)
    run_sub_pulse(int(PULSE_PEAK_BRIGHTNESS * DUB_BRIGHTNESS_RATIO), spb * DUB_DURATION_PCT)

def pulse_engine():
    global heartBeat_bpm
    while True:
        if (heartBeat_bpm < 1 or is_recovering) and not game_active:
            GPIO.output(in1, GPIO.LOW); GPIO.output(in2, GPIO.LOW); p.ChangeDutyCycle(0)
            if not is_recovering and not dance_is_running and not game_active: 
                set_all_leds(Color(0,0,0), OFF_PULSE_BRIGHTNESS)
            time.sleep(0.2); continue
            
        # ZERO DIVISION FIX
        sec_per_beat = 60.0 / heartBeat_bpm if heartBeat_bpm > 0 else 1.0
        
        if not dance_is_running and not game_active: 
            threading.Thread(target=heartBeat_led_pulse, args=(heartBeat_bpm,), daemon=True).start()
            
        trigger_motor_pulse()
        rest_time = max(0, sec_per_beat - MOTOR_PULSE_DURATION)
        while rest_time > 0:
            if (is_recovering or heartBeat_bpm < 1) and not game_active: break
            time.sleep(min(0.05, rest_time)); rest_time -= 0.05

#### LOGIC FUNCTIONS ####
def check_secret_immediate(pin):
    """ Detects secret codes. Returns HIBERNATE, START_GAME, or False """
    global current_sequence, heartBeat_bpm, is_recovering, last_input_time, last_secret_press_time, game_active
    with button_lock:
        now = time.time()
        if len(current_sequence) > 0 and (now - last_secret_press_time) > SECRET_TIMEOUT:
            current_sequence = []
        current_sequence.append(pin); last_secret_press_time = now
        
        if current_sequence == secret_code_hibernation:
            heartBeat_bpm = 0; is_recovering = True; current_sequence = []
            threading.Thread(target=hibernation_visual, daemon=True).start()
            return "HIBERNATE"
        
        if current_sequence == secret_code_game:
            current_sequence = []
            game_active = True # Breaks dance immediately
            return "START_GAME"
            
        if len(current_sequence) >= 4: current_sequence = []
        return False

def gradual_stop():
    global heartBeat_bpm, is_stopping
    if heartBeat_bpm <= 0 or is_stopping: return
    is_stopping = True; start_bpm = heartBeat_bpm; steps = 20
    for _ in range(steps):
        if heartBeat_bpm <= 0 or is_recovering: break
        heartBeat_bpm = max(0, heartBeat_bpm - (start_bpm / steps))
        time.sleep(STOP_DURATION / steps)
    if not is_recovering: heartBeat_bpm = 0
    is_stopping = False

#### MAIN ####
if __name__ == '__main__':
    try:
        set_all_leds(Color(0,0,0), OFF_PULSE_BRIGHTNESS)
        while True:
            if GPIO.input(BUTTON_FAST) == GPIO.HIGH:
                heartBeat_bpm = INITIAL_START_BPM; last_input_time = time.time(); break
            if GPIO.input(BUTTON_SLOW) == GPIO.HIGH:
                heartBeat_bpm = INITIAL_START_BPM; last_input_time = time.time()
                while GPIO.input(BUTTON_SLOW) == GPIO.HIGH: time.sleep(0.05)
                break
            time.sleep(0.1)
        
        threading.Thread(target=pulse_engine, daemon=True).start()

        while True:
            now = time.time()
            f_raw, s_raw = GPIO.input(BUTTON_FAST), GPIO.input(BUTTON_SLOW)
            
            if not burn_mode_active and datetime.datetime.now() >= BURN_START_TIME:
                burn_mode_active = True
                if heartBeat_bpm == 0: heartBeat_bpm = INITIAL_START_BPM

            # Note: Removed dance check here so buttons stay live during idle dance
            if not game_active:
                if heartBeat_bpm == 0 and not is_recovering and not burn_mode_active:
                    if len(current_sequence) > 0 and (now - last_secret_press_time) > SECRET_TIMEOUT:
                        with button_lock: current_sequence = []
                    
                    if idle_start_time is None: 
                        idle_start_time = now; current_idle_goal = IDLE_DANCE_TIMEOUT + random.uniform(0, IDLE_JITTER_MAX)
                    elif (now - idle_start_time) > current_idle_goal and not dance_triggered: 
                        threading.Thread(target=dance_visual, daemon=True).start(); dance_triggered = True
                else: idle_start_time = None; dance_triggered = False

                if not burn_mode_active and (now - last_input_time) > current_decay_delay:
                    if heartBeat_bpm > 0: heartBeat_bpm = max(0, heartBeat_bpm - DECAY_STEP); time.sleep(DECAY_TICK_RATE)
                    elif is_recovering: is_recovering = False

                               
                # --- DUAL BUTTON HOLD DETECTION ---
                if f_raw == GPIO.HIGH and s_raw == GPIO.HIGH and heartBeat_bpm > 0:
                    dual_hold_active = True
                    
                    # Pick a new random start hue each time the hold begins
                    start_hue = random.random()
                    hold_start = time.time()
                    
                    debug_log(f"[MODE] Dual Hold Active - Starting Hue: {start_hue:.2f}")
                    
                    while GPIO.input(BUTTON_FAST) == GPIO.HIGH and GPIO.input(BUTTON_SLOW) == GPIO.HIGH:
                        loop_now = time.time()
                        elapsed = loop_now - hold_start
                        
                        # Calculate hue: Start + (Time * Speed)
                        cycle_hue = (start_hue + (elapsed * CYCLE_SPEED)) % 1.0
                        
                        last_input_time = loop_now
                        time.sleep(0.05)
                    
                    dual_hold_active = False
                    debug_log("[MODE] Dual Hold Released")
                    continue

                if not is_recovering:
                    # --- FAST BUTTON ---
                    if f_raw == GPIO.HIGH:
                        last_input_time = now
                        status = check_secret_immediate(BUTTON_FAST)
                        if status == "START_GAME":
                            time.sleep(2)
                            run_full_game_progression()
                            continue
                        elif status == "HIBERNATE": continue

                        if heartBeat_bpm == 0: heartBeat_bpm = INITIAL_START_BPM
                        else: 
                            inc = BURN_BPM_INCREMENT if burn_mode_active else BPM_INCREMENT_FAST
                            heartBeat_bpm = min(heartBeat_bpm + inc, MOTOR_MAX_BPM)
                        
                        last_tick = time.time()
                        while GPIO.input(BUTTON_FAST) == GPIO.HIGH:
                            loop_now = time.time()
                            if loop_now - last_tick >= 1.0: 
                                heartBeat_bpm = min(heartBeat_bpm + HOLD_BPM_CHANGE, MOTOR_MAX_BPM)
                                last_tick = loop_now; last_input_time = loop_now
                            time.sleep(0.05)

                    # --- SLOW BUTTON ---
                    elif s_raw == GPIO.HIGH:
                        last_input_time = now
                        status = check_secret_immediate(BUTTON_SLOW)
                        if status == "START_GAME":
                            time.sleep(2)
                            run_full_game_progression()
                            continue
                        elif status == "HIBERNATE": continue

                        if burn_mode_active: 
                            heartBeat_bpm = min(heartBeat_bpm + BURN_BPM_INCREMENT, MOTOR_MAX_BPM)
                            while GPIO.input(BUTTON_SLOW) == GPIO.HIGH: time.sleep(0.05)
                        else:
                            press_start = time.time(); last_tick = press_start; held_long = False
                            while GPIO.input(BUTTON_SLOW) == GPIO.HIGH:
                                loop_now = time.time()
                                if loop_now - press_start >= SLOW_HOLD_THRESHOLD:
                                    held_long = True
                                    if loop_now - last_tick >= 1.0: 
                                        heartBeat_bpm = max(0, heartBeat_bpm - HOLD_BPM_CHANGE)
                                        last_tick = loop_now; last_input_time = loop_now
                                time.sleep(0.05)
                            if not held_long: threading.Thread(target=gradual_stop, daemon=True).start()
            time.sleep(0.05)
    except KeyboardInterrupt: pass
    finally: GPIO.output(in1, GPIO.LOW); GPIO.output(in2, GPIO.LOW); p.stop(); GPIO.cleanup()