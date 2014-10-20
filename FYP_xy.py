import wiringpi2 as wp
import threading
import array
import numpy as np
import time

wp.wiringPiSetup() # Prepares the RPi GPIO pins

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
X_MIN = 0
X_MAX = 8
X_MID = (X_MAX - X_MIN) / 2
Y_MIN = 0
Y_MAX = 8
Y_MID = (Y_MAX - Y_MIN) / 2

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

# Array initialisation
values = np.zeros([COUNT_MAX], dtype=int)
sections = np.zeros([16], dtype=int)
ave = np.zeros([3, AVERAGING_PERIOD], dtype=int)
x0 = np.zeros([3], dtype=int)
I_cal = np.zeros([7, 3], dtype=int)
x_cal = np.array([X_MIN, X_MAX, X_MAX, X_MIN, X_MIN, X_MID, X_MID], dtype=float)
y_cal = np.array([Y_MIN, Y_MIN, Y_MAX, Y_MAX, Y_MID, Y_MID, Y_MIN], dtype=float)

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

# Initialise display
def lcd_init():
	lcd_byte(0x33,LCD_CMD)
	lcd_byte(0x32,LCD_CMD)
	lcd_byte(0x28,LCD_CMD)
	lcd_byte(0x0C,LCD_CMD)
	lcd_byte(0x06,LCD_CMD)
	lcd_byte(0x01,LCD_CMD)

# Send string to display
def lcd_string(message):
	message = message.ljust(LCD_WIDTH," ")
	
	for i in range(LCD_WIDTH):
		lcd_byte(ord(message[i]),LCD_CHR)
		
# Send byte to data pins
# bits = data
# mode = True  for character
#        False for command
def lcd_byte(bits, mode):
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

# Read the ADC channel
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
	
# Remove outliers from an array of data
def average_average(data):
	d = np.abs(data - np.median(data))
	x = data[d < OUTLIER_THRESH]
	if(np.any(x)): return int(round(np.mean(x)))
	else: return 0

# Calibrate the device for localisation	
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
		if(count > 15):
			broken_out = 1
			break
	
	# If found the correct break points
	if(broken_out):
		print "Broken! ", sections
		max_diff = 0
		start_section = 0
		
		# Find the sections in the signal
		for i in range(8):
			if(sections[i+1]-sections[i] > max_diff):
				max_diff = sections[i+1]-sections[i]
				start_section = i+1
		print "Broken! ", sections, " Start: ", start_section
		
		# Find the intensities
		for i in range(4):
			diff = sections[start_section+1+2*i]-sections[start_section+2*i]
			print "Diff: ", diff
			sum = 0
			for j in range(diff):
				sum += values[sections[start_section+2*i]+j]
			if(i==0):
				zero_lvl = sum / diff
				print "Zero lvl: ", zero_lvl
			else:
				I_cal[position, i-1] = sum / diff - zero_lvl
				print "Read: ", sum, ", ", sum / diff, ", ", I_cal[position, i-1]
		print I_cal
		return 1
	
	# If the calibration failed (due to illogical readings)
	else: 	# Display some text on the LCD screen
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
# Initial stage, only runs once
print "Beginning calibration! First reading in 10 seconds"
lcd_byte(LCD_LINE_1, LCD_CMD)
lcd_string("Calibration!")
lcd_byte(LCD_LINE_2, LCD_CMD)
lcd_string("Prepare the rec.")
time.sleep(5)

# Calibration stage, runs until a successful calibration is detected
passed_cal = 0
while not passed_cal:
	passed_cal = 1
	for i in range(7):
		lcd_byte(LCD_LINE_1, LCD_CMD)
		lcd_string("[" + str(x_cal[i]) + ", " + str(y_cal[i]) + "]")
		for t in range(CAL_TIME+1):
			lcd_byte(LCD_LINE_2, LCD_CMD)
			lcd_string(str((i+1)) + "/7, " + str((CAL_TIME-t)) + "sec")
			time.sleep(1)
		tmp = calibrate(i)
		print tmp
		if(tmp==0):
			passed_cal = 0
			break

# Creating the array to find X and Y calibration coefficients
cal_array_0 = np.array([[pow(I_cal[0, 0], 2), pow(I_cal[0, 1], 2), pow(I_cal[0, 2], 2), I_cal[0, 0], I_cal[0, 1], I_cal[0, 2], 1],
						[pow(I_cal[1, 0], 2), pow(I_cal[1, 1], 2), pow(I_cal[1, 2], 2), I_cal[1, 0], I_cal[1, 1], I_cal[1, 2], 1],
						[pow(I_cal[2, 0], 2), pow(I_cal[2, 1], 2), pow(I_cal[2, 2], 2), I_cal[2, 0], I_cal[2, 1], I_cal[2, 2], 1],
						[pow(I_cal[3, 0], 2), pow(I_cal[3, 1], 2), pow(I_cal[3, 2], 2), I_cal[3, 0], I_cal[3, 1], I_cal[3, 2], 1],
						[pow(I_cal[4, 0], 2), pow(I_cal[4, 1], 2), pow(I_cal[4, 2], 2), I_cal[4, 0], I_cal[4, 1], I_cal[4, 2], 1],
						[pow(I_cal[5, 0], 2), pow(I_cal[5, 1], 2), pow(I_cal[5, 2], 2), I_cal[5, 0], I_cal[5, 1], I_cal[5, 2], 1],
						[pow(I_cal[6, 0], 2), pow(I_cal[6, 1], 2), pow(I_cal[6, 2], 2), I_cal[6, 0], I_cal[6, 1], I_cal[6, 2], 1]])

print cal_array_0

cal_out_0 = np.linalg.solve(cal_array_0, x_cal)	# Solving X calibration coefficients			
cal_out_1 = np.linalg.solve(cal_array_0, y_cal) # Solving Y calibration coefficients

print cal_out_0
print cal_out_1

# Main loop
while True:
	meta_count = 0	
	while(meta_count < AVERAGING_PERIOD): # Collect samples until a set number of consecutive samples are accurate
		for count in range(COUNT_MAX): # Collect a set number of ADC readings 
			readadc(adcnum, SPICLK, SPIMOSI, SPIMISO, SPICS, count)
			
		broken_out = 0
		count = 0
		for i in range(COUNT_MAX-1):
			#print "1: ", values[i+1], "\t2: ", values[i], "\tabs: ", abs(values[i+1]-values[i])
			if(abs(values[i+1]-values[i]) > THRESH):
				sections[count] = i+1
				count += 1
			if(count > 15):
				broken_out = 1
				break
		
		# Identify the sections that form the signal from the received values
		if(broken_out):
			#print "Broken! ", sections
			max_diff = 0
			start_section = 0
			
			for i in range(8):
				if(sections[i+1]-sections[i] > max_diff):
					max_diff = sections[i+1]-sections[i]
					start_section = i+1
			#print "Broken! ", sections, " Start: ", start_section
			
			# Find the average of each of the sections to represent that section
			for i in range(4):
				diff = sections[start_section+1+2*i]-sections[start_section+2*i]
				sum = 0
				for j in range(diff):
					sum += values[sections[start_section+2*i]+j]
				if(i==0):
					zero_lvl = sum / diff
				else:
					ave[i-1, meta_count] = sum / diff - zero_lvl
				
			meta_count = meta_count + 1
					
		else: 	# Print invalid if enough sections are not found
			lcd_byte(LCD_LINE_1, LCD_CMD)
			lcd_string("Invalid")
			lcd_byte(LCD_LINE_2, LCD_CMD)
			lcd_string("conditions")
			print "Invalid lighting conditions!"
				
			meta_count = 0
		
	# Remove the outliers of the averages
	for i in range(3):
		x0[i] = average_average(ave[i, :])
	
	# If there is a valid amount of data to work with, calculate the position of the device and print to display
	if(np.amin(x0) > 0):
		x = cal_out_0[0]*pow(x0[0], 2)+cal_out_0[1]*pow(x0[1], 2)+cal_out_0[2]*pow(x0[2], 2)+cal_out_0[3]*x0[0]+cal_out_0[4]*x0[1]+cal_out_0[5]*x0[2]+cal_out_0[6]
		y = cal_out_1[0]*pow(x0[0], 2)+cal_out_1[1]*pow(x0[1], 2)+cal_out_1[2]*pow(x0[2], 2)+cal_out_1[3]*x0[0]+cal_out_1[4]*x0[1]+cal_out_1[5]*x0[2]+cal_out_1[6]
		# Display some text on the LCD screen
		lcd_byte(LCD_LINE_1, LCD_CMD)
		lcd_string("[x, y]")
		lcd_byte(LCD_LINE_2, LCD_CMD)
		lcd_string("[" + format(x, '.3f') + ", " + format(y, '.3f') + "]") # Format the coordinates to 3 decimal places and output to the screen
		print "[", x, ", ", y, "] 1:\t", x0[0], "\t2:\t", x0[1], "\t3:\t", x0[2]
	
	# If the device detects fluctuating responses, display an error until it is corrected
	else:
		lcd_byte(LCD_LINE_1, LCD_CMD)
		lcd_string("Unsteady!")
		lcd_byte(LCD_LINE_2, LCD_CMD)
		lcd_string("Pls stabilise!")
		print "Unsteady! Please stabilise."

