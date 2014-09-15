import wiringpi2 as wp
import threading
import array
import numpy as np
import time

wp.wiringPiSetup()

# Define the LCD pins
LCD_RS = 7
LCD_E  = 2
LCD_D4 = 13
LCD_D5 = 14
LCD_D6 = 12
LCD_D7 = 3

# Define the ADC pins
SPICLK = 11
SPIMISO = 10
SPIMOSI = 6
SPICS = 5

# Constants
COUNT_MAX = 200
THRESH = 50
OUTLIER_THRESH = 20
AVERAGING_PERIOD = 10
CAL_TIME = 10
# LCD constants
LCD_WIDTH = 16    # Maximum characters per line
LCD_CHR = 1
LCD_CMD = 0
LCD_LINE_1 = 0x80 # LCD RAM address for the 1st line
LCD_LINE_2 = 0xC0 # LCD RAM address for the 2nd line 
# Timing constants
E_PULSE = 0.00005
E_DELAY = 0.00005

# Variable initialisation
adcnum = 0
meta_count = 0
values = np.zeros([COUNT_MAX], dtype=int)
sections = np.zeros([12], dtype=int)
ave = np.zeros([3, AVERAGING_PERIOD], dtype=int)
x0 = np.zeros([3], dtype=int)
I_cal = np.zeros([6, 3], dtype=int)
x_cal = np.array([0, 1, 1, 0, 0, 0.5], dtype=int)
y_cal = np.array([0, 0, 1, 1, 0.5, 0.5], dtype=int)

# Mode setting for LCD pins
wp.pinMode(LCD_E, 1)  # E
wp.pinMode(LCD_RS, 1) # RS
wp.pinMode(LCD_D4, 1) # DB4
wp.pinMode(LCD_D5, 1) # DB5
wp.pinMode(LCD_D6, 1) # DB6
wp.pinMode(LCD_D7, 1) # DB7

# Mode setting for ADC pins
wp.pinMode(SPICLK, 1)
wp.pinMode(SPIMISO, 0)
wp.pinMode(SPIMOSI, 1)
wp.pinMode(SPICS, 1)

def lcd_init():
	# Initialise display
	lcd_byte(0x33,LCD_CMD)
	lcd_byte(0x32,LCD_CMD)
	lcd_byte(0x28,LCD_CMD)
	lcd_byte(0x0C,LCD_CMD)
	lcd_byte(0x06,LCD_CMD)
	lcd_byte(0x01,LCD_CMD)

def lcd_string(message):
	# Send string to display
	message = message.ljust(LCD_WIDTH," ")
	
	for i in range(LCD_WIDTH):
		lcd_byte(ord(message[i]),LCD_CHR)

def lcd_byte(bits, mode):
	# Send byte to data pins
	# bits = data
	# mode = True  for character
	#        False for command
	
	wp.digitalWrite(LCD_RS, mode) # RS
	
	# High bits
	wp.digitalWrite(LCD_D4, 0)
	wp.digitalWrite(LCD_D5, 0)
	wp.digitalWrite(LCD_D6, 0)
	wp.digitalWrite(LCD_D7, 0)
	if bits&0x10==0x10:
		wp.digitalWrite(LCD_D4, 1)
	if bits&0x20==0x20:
		wp.digitalWrite(LCD_D5, 1)
	if bits&0x40==0x40:
		wp.digitalWrite(LCD_D6, 1)
	if bits&0x80==0x80:
		wp.digitalWrite(LCD_D7, 1)
	
	# Toggle 'Enable' pin
	time.sleep(E_DELAY)
	wp.digitalWrite(LCD_E, 1)
	time.sleep(E_PULSE)
	wp.digitalWrite(LCD_E, 0)
	time.sleep(E_DELAY)
	
	# Low bits
	wp.digitalWrite(LCD_D4, 0)
	wp.digitalWrite(LCD_D5, 0)
	wp.digitalWrite(LCD_D6, 0)
	wp.digitalWrite(LCD_D7, 0)
	if bits&0x01==0x01:
		wp.digitalWrite(LCD_D4, 1)
	if bits&0x02==0x02:
		wp.digitalWrite(LCD_D5, 1)
	if bits&0x04==0x04:
		wp.digitalWrite(LCD_D6, 1)
	if bits&0x08==0x08:
		wp.digitalWrite(LCD_D7, 1)
	
	# Toggle 'Enable' pin
	time.sleep(E_DELAY)
	wp.digitalWrite(LCD_E, 1)
	time.sleep(E_PULSE)
	wp.digitalWrite(LCD_E, 0)
	time.sleep(E_DELAY)  

def readadc(adcnum, clockpin, mosipin, misopin, cspin, count):
	if((adcnum > 7) or (adcnum < 0)):
		return -1
	
	wp.digitalWrite(cspin, 1)
	wp.digitalWrite(clockpin, 0) 	# start clock low
	wp.digitalWrite(cspin, 0)		# bring CS low
	
	commandout = adcnum
	commandout |= 0x18	# start bit + single-ended bit
	commandout <<= 3	# we only need to send 5 bits here
	
	for i in range(5):
		if(commandout & 0x80):
			wp.digitalWrite(mosipin, 1)
		else:
			wp.digitalWrite(mosipin, 0)
			
		commandout <<= 1
		wp.digitalWrite(clockpin, 1)
		wp.digitalWrite(clockpin, 0)
	
	adcout = 0
	# read in one empty bit, one null bit and 10 adc bits
	for i in range (12):
		wp.digitalWrite(clockpin, 1)
		wp.digitalWrite(clockpin, 0)
		adcout <<= 1
		if(wp.digitalRead(misopin)):
			adcout |= 0x1
			
	wp.digitalWrite(cspin, 1)
	
	adcout /= 2
	values[count] = adcout
	#print "Analog read =", adcout
	#return adcout
	
def average_average(data):
	d = np.abs(data - np.median(data))
	x = data[d < OUTLIER_THRESH]
	if(np.any(x)): return int(round(np.mean(x)))
	else: return 0
	
def calibrate(position):
	for count in range(COUNT_MAX):
		readadc(adcnum, SPICLK, SPIMOSI, SPIMISO, SPICS, count)
		
	broken_out = 0
	count = 0
	for i in range(COUNT_MAX-1):
		#print "1: ", values[i+1], "\t2: ", values[i], "\tabs: ", abs(values[i+1]-values[i])
		if(abs(values[i+1]-values[i]) > THRESH):
			sections[count] = i+1
			count += 1
		if(count > 11):
			broken_out = 1
			break
			
	if(broken_out):
		print "Broken! ", sections
		max_diff = 0
		start_section = 0
		
		for i in range(6):
			if(sections[i+1]-sections[i] > max_diff):
				max_diff = sections[i+1]-sections[i]
				start_section = i+1
		print "Broken! ", sections, " Start: ", start_section
		
		for i in range(3):
			diff = sections[start_section+1+2*i]-sections[start_section+2*i]
			sum = 0
			for j in range(diff):
				sum += values[sections[start_section+2*i]+j]
			I_cal[position, i] = sum / diff
		print I_cal
		return 1
				
	else: 	# Send some test
		lcd_byte(LCD_LINE_1, LCD_CMD)
		lcd_string("Invalid")
		lcd_byte(LCD_LINE_2, LCD_CMD)
		lcd_string("calibration")
		print "Invalid calibration, please reattempt"
		time.sleep(5)
		return 0
	
# Initialise display
lcd_init()

# Calibration routine

print "Beginning calibration! First reading in 10 seconds"
lcd_byte(LCD_LINE_1, LCD_CMD)
lcd_string("Calibration!")
lcd_byte(LCD_LINE_2, LCD_CMD)
lcd_string("Prepare the rec.")
time.sleep(5)

passed_cal = 0
while not passed_cal:
	passed_cal = 1
	for i in range(6):
		lcd_byte(LCD_LINE_1, LCD_CMD)
		lcd_string("[" + str(x_cal[i]) + ", " + str(y_cal[i]) + "]")
		for t in range(CAL_TIME+1):
			lcd_byte(LCD_LINE_2, LCD_CMD)
			lcd_string(str((i+1)) + "/6, " + str((CAL_TIME-t)) + "sec")
			time.sleep(1)
		tmp = calibrate(i)
		print tmp
		if(tmp==0):
			passed_cal = 0
			break

cal_array_0 = np.array([[I_cal[0, 0]*x_cal[0], I_cal[0, 1]*x_cal[0], I_cal[0, 0]*y_cal[0], I_cal[0, 1]*y_cal[0], I_cal[0, 0], I_cal[0, 1]],
				[I_cal[1, 0]*x_cal[1], I_cal[1, 1]*x_cal[1], I_cal[1, 0]*y_cal[1], I_cal[1, 1]*y_cal[1], I_cal[1, 0], I_cal[1, 1]],
				[I_cal[2, 0]*x_cal[2], I_cal[2, 1]*x_cal[2], I_cal[2, 0]*y_cal[2], I_cal[2, 1]*y_cal[2], I_cal[2, 0], I_cal[2, 1]],
				[I_cal[3, 0]*x_cal[3], I_cal[3, 1]*x_cal[3], I_cal[3, 0]*y_cal[3], I_cal[3, 1]*y_cal[3], I_cal[3, 0], I_cal[3, 1]],
				[I_cal[4, 0]*x_cal[4], I_cal[4, 1]*x_cal[4], I_cal[4, 0]*y_cal[4], I_cal[4, 1]*y_cal[4], I_cal[4, 0], I_cal[4, 1]],
				[I_cal[5, 0]*x_cal[5], I_cal[5, 1]*x_cal[5], I_cal[5, 0]*y_cal[5], I_cal[5, 1]*y_cal[5], I_cal[5, 0], I_cal[5, 1]]])

cal_array_1 = np.array([[I_cal[0, 0]*x_cal[0], I_cal[0, 2]*x_cal[0], I_cal[0, 0]*y_cal[0], I_cal[0, 2]*y_cal[0], I_cal[0, 0], I_cal[0, 2]],
				[I_cal[1, 0]*x_cal[1], I_cal[1, 2]*x_cal[1], I_cal[1, 0]*y_cal[1], I_cal[1, 2]*y_cal[1], I_cal[1, 0], I_cal[1, 2]],
				[I_cal[2, 0]*x_cal[2], I_cal[2, 2]*x_cal[2], I_cal[2, 0]*y_cal[2], I_cal[2, 2]*y_cal[2], I_cal[2, 0], I_cal[2, 2]],
				[I_cal[3, 0]*x_cal[3], I_cal[3, 2]*x_cal[3], I_cal[3, 0]*y_cal[3], I_cal[3, 2]*y_cal[3], I_cal[3, 0], I_cal[3, 2]],
				[I_cal[4, 0]*x_cal[4], I_cal[4, 2]*x_cal[4], I_cal[4, 0]*y_cal[4], I_cal[4, 2]*y_cal[4], I_cal[4, 0], I_cal[4, 2]],
				[I_cal[5, 0]*x_cal[5], I_cal[5, 2]*x_cal[5], I_cal[5, 0]*y_cal[5], I_cal[5, 2]*y_cal[5], I_cal[5, 0], I_cal[5, 2]]])

cal_out_0 = np.linalg.solve(cal_array_0, np.zeros([6], dtype=int))				
cal_out_1 = np.linalg.solve(cal_array_1, np.zeros([6], dtype=int))

print cal_out_0
print cal_out_1
print cal_array_0
print cal_array_1

# Main loop
while True:
	meta_count = 0	
	while(meta_count < AVERAGING_PERIOD):
		for count in range(COUNT_MAX):
			readadc(adcnum, SPICLK, SPIMOSI, SPIMISO, SPICS, count)
			
		broken_out = 0
		count = 0
		for i in range(COUNT_MAX-1):
			#print "1: ", values[i+1], "\t2: ", values[i], "\tabs: ", abs(values[i+1]-values[i])
			if(abs(values[i+1]-values[i]) > THRESH):
				sections[count] = i+1
				count += 1
			if(count > 11):
				broken_out = 1
				break
				
		if(broken_out):
			#print "Broken! ", sections
			max_diff = 0
			start_section = 0
			
			for i in range(6):
				if(sections[i+1]-sections[i] > max_diff):
					max_diff = sections[i+1]-sections[i]
					start_section = i+1
			#print "Broken! ", sections, " Start: ", start_section
			
			for i in range(3):
				diff = sections[start_section+1+2*i]-sections[start_section+2*i]
				sum = 0
				for j in range(diff):
					sum += values[sections[start_section+2*i]+j]
				ave[i, meta_count] = sum / diff
				
			meta_count = meta_count + 1
					
		else: 	# Send some test
			lcd_byte(LCD_LINE_1, LCD_CMD)
			lcd_string("Invalid")
			lcd_byte(LCD_LINE_2, LCD_CMD)
			lcd_string("conditions")
			print "Invalid lighting conditions!"
				
			meta_count = 0
		
	for i in range(3):
		x0[i] = average_average(ave[i, :])
	
	if(np.amin(x0) > 0):	
		# Send some test
		lcd_byte(LCD_LINE_1, LCD_CMD)
		lcd_string("1:" + str(x0[0]) + " 2:" + str(x0[1]))
		lcd_byte(LCD_LINE_2, LCD_CMD)
		lcd_string("3:" + str(x0[2]))
		print "1:\t", x0[0], "\t2:\t", x0[1], "\t3:\t", x0[2]

	else:
		lcd_byte(LCD_LINE_1, LCD_CMD)
		lcd_string("Unsteady!")
		lcd_byte(LCD_LINE_2, LCD_CMD)
		lcd_string("Pls stabilise!")
		print "Unsteady! Please stabilise."

