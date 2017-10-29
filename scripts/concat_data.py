import os

DATA_DIR = "/Users/evanmdoyle/Programming/ChessAI/DerivedData/"
GAME_DIR = "/Users/evanmdoyle/Programming/ChessAI/StockfishMirrorMatches/"

DATA_SUBDIRS = ['off_heatmaps/', 'def_heatmaps/']
SUBDIR_NAMES = [s[:-2]+"_" for s in DATA_SUBDIRS]

DST_DIR = DATA_DIR + "complete/"

for data_file in os.listdir(os.fsencode(GAME_DIR)):
	file_name = os.fsdecode(data_file)
	file_contents = {}
	file_length = 0
	for k in range(len(DATA_SUBDIRS)):
		with open(
			DATA_DIR+DATA_SUBDIRS[k]+SUBDIR_NAMES[k]+file_name[:-4]+".csv",
			'r') as f:
			file_contents[DATA_SUBDIRS[k]] = f.readlines()
			# Assume file_length is same for all files
			file_length = len(file_contents[DATA_SUBDIRS[k]])
	with open(DST_DIR+file_name[:-4]+".csv", 'w') as f:
		for i in range(file_length):
			for subdir in file_contents:
				for line in [arr[:-1] for arr in file_contents[subdir]]:
					f.write(line)
			f.write('\n')
