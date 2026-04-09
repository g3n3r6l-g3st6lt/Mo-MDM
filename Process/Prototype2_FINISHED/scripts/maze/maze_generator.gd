class_name MazeGenerator
extends RefCounted

# The block grid: 0 = open floor, 1 = solid wall, 2 = principle-tagged wall
var cells: Dictionary = {}
var cell_tags: Dictionary = {}  # position -> [principle_id]

var block_width: int
var block_height: int
var rooms_wide: int
var rooms_tall: int

var goal: Vector2i = Vector2i.ZERO
var threshold_spots: Array = []
var dead_end_rooms: Array = []

# Room distances from start (for threshold placement)
var room_distance: Dictionary = {}

var rng: RandomNumberGenerator
var principle_ids: Array = []
var shortcut_chance: float = 0.25
var threshold_count: int = 3


func _init(width: int = 9, height: int = 9, seed_value: int = -1) -> void:
	rooms_wide = width
	rooms_tall = height
	block_width = width * 2 + 1
	block_height = height * 2 + 1
	rng = RandomNumberGenerator.new()
	if seed_value >= 0:
		rng.seed = seed_value
	else:
		rng.randomize()


func build(held_principle_ids: Array, config: Dictionary = {}) -> Dictionary:
	principle_ids = held_principle_ids
	if config.has("shortcut_chance"):
		shortcut_chance = config["shortcut_chance"]
	if config.has("thresholds"):
		threshold_count = config["thresholds"]
	_fill_grid()
	_carve_corridors()
	_measure_distances()
	_find_dead_ends()
	_add_shortcuts()
	_place_thresholds_at_junctions()
	_set_goal()
	return cells


# Fill everything with walls, then open the room cells
func _fill_grid() -> void:
	cells.clear()
	cell_tags.clear()
	for x: int in range(block_width):
		for y: int in range(block_height):
			cells[Vector2i(x, y)] = 1
	for rx: int in range(rooms_wide):
		for ry: int in range(rooms_tall):
			cells[room_to_block(rx, ry)] = 0


# Recursive backtracker to carve passages between rooms
func _carve_corridors() -> void:
	var visited: Dictionary = {}
	var stack: Array = []
	var start: Vector2i = Vector2i(0, 0)
	visited[start] = true
	stack.append(start)

	while not stack.is_empty():
		var current: Vector2i = stack.back()
		var unvisited: Array = _unvisited_neighbors(current, visited)
		if unvisited.is_empty():
			stack.pop_back()
		else:
			var next_room: Vector2i = unvisited[rng.randi() % unvisited.size()]
			var wall_between: Vector2i = _wall_cell_between(current, next_room)
			cells[wall_between] = 0
			visited[next_room] = true
			stack.append(next_room)


func _unvisited_neighbors(room: Vector2i, visited: Dictionary) -> Array:
	var neighbors: Array = []
	for offset: Vector2i in [Vector2i(0,-1), Vector2i(0,1), Vector2i(-1,0), Vector2i(1,0)]:
		var neighbor: Vector2i = room + offset
		if neighbor.x >= 0 and neighbor.x < rooms_wide and neighbor.y >= 0 and neighbor.y < rooms_tall:
			if neighbor not in visited:
				neighbors.append(neighbor)
	return neighbors


func _wall_cell_between(room_a: Vector2i, room_b: Vector2i) -> Vector2i:
	var a: Vector2i = room_to_block(room_a.x, room_a.y)
	var b: Vector2i = room_to_block(room_b.x, room_b.y)
	return Vector2i((a.x + b.x) / 2, (a.y + b.y) / 2)


# BFS from start to measure how far each room is
func _measure_distances() -> void:
	room_distance.clear()
	var queue: Array = [Vector2i(0, 0)]
	room_distance[Vector2i(0, 0)] = 0
	while not queue.is_empty():
		var current: Vector2i = queue.pop_front()
		var depth: int = room_distance[current]
		for offset: Vector2i in [Vector2i(0,-1), Vector2i(0,1), Vector2i(-1,0), Vector2i(1,0)]:
			var neighbor: Vector2i = current + offset
			if neighbor.x >= 0 and neighbor.x < rooms_wide and neighbor.y >= 0 and neighbor.y < rooms_tall:
				if neighbor not in room_distance:
					var wall: Vector2i = _wall_cell_between(current, neighbor)
					if cells[wall] == 0:
						room_distance[neighbor] = depth + 1
						queue.append(neighbor)


# Find rooms with only one open connection (dead ends)
func _find_dead_ends() -> void:
	dead_end_rooms.clear()
	for room: Vector2i in room_distance:
		var open_passages: int = 0
		for offset: Vector2i in [Vector2i(0,-1), Vector2i(0,1), Vector2i(-1,0), Vector2i(1,0)]:
			var neighbor: Vector2i = room + offset
			if neighbor.x >= 0 and neighbor.x < rooms_wide and neighbor.y >= 0 and neighbor.y < rooms_tall:
				var wall: Vector2i = _wall_cell_between(room, neighbor)
				if cells[wall] == 0:
					open_passages += 1
		if open_passages <= 1:
			dead_end_rooms.append(room_to_block(room.x, room.y))


# Tag some remaining walls with principles (create conditional shortcuts)
func _add_shortcuts() -> void:
	if principle_ids.is_empty():
		return
	for rx: int in range(rooms_wide):
		for ry: int in range(rooms_tall):
			for offset: Vector2i in [Vector2i(1, 0), Vector2i(0, 1)]:
				var neighbor: Vector2i = Vector2i(rx, ry) + offset
				if neighbor.x >= 0 and neighbor.x < rooms_wide and neighbor.y >= 0 and neighbor.y < rooms_tall:
					var wall: Vector2i = _wall_cell_between(Vector2i(rx, ry), neighbor)
					if cells[wall] == 1:
						if rng.randf() < shortcut_chance:
							cells[wall] = 2
							var tag: StringName = principle_ids[rng.randi() % principle_ids.size()]
							cell_tags[wall] = [tag]


# Place thresholds at rooms with 3+ open connections (intersections)
func _place_thresholds_at_junctions() -> void:
	threshold_spots.clear()
	var max_distance: int = 0
	for room: Vector2i in room_distance:
		if room_distance[room] > max_distance:
			max_distance = room_distance[room]

	# Find all intersection rooms (3+ open passages) sorted by distance
	var junctions: Array = []
	for room: Vector2i in room_distance:
		var open_passages: int = 0
		for offset: Vector2i in [Vector2i(0,-1), Vector2i(0,1), Vector2i(-1,0), Vector2i(1,0)]:
			var neighbor: Vector2i = room + offset
			if neighbor.x >= 0 and neighbor.x < rooms_wide and neighbor.y >= 0 and neighbor.y < rooms_tall:
				var wall: Vector2i = _wall_cell_between(room, neighbor)
				if cells[wall] == 0:
					open_passages += 1
		if open_passages >= 3:
			junctions.append({"room": room, "distance": room_distance[room]})

	# Sort by distance so we can pick evenly spaced ones
	junctions.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return a["distance"] < b["distance"]
	)

	# Pick thresholds evenly spaced through the distance range
	var interval: int = maxi(1, max_distance / (threshold_count + 1))
	for i: int in range(1, threshold_count + 1):
		var target_distance: int = interval * i
		var best_junction: Dictionary = {}
		var best_gap: int = 999
		for junction: Dictionary in junctions:
			var already_used: bool = false
			for existing: Vector2i in threshold_spots:
				if existing == room_to_block(junction["room"].x, junction["room"].y):
					already_used = true
					break
			if already_used:
				continue
			var gap: int = absi(junction["distance"] - target_distance)
			if gap < best_gap:
				best_gap = gap
				best_junction = junction
		if not best_junction.is_empty():
			threshold_spots.append(room_to_block(best_junction["room"].x, best_junction["room"].y))


# Goal is the room farthest from start
func _set_goal() -> void:
	var max_distance: int = 0
	var farthest: Vector2i = Vector2i.ZERO
	for room: Vector2i in room_distance:
		if room_distance[room] > max_distance:
			max_distance = room_distance[room]
			farthest = room
	goal = room_to_block(farthest.x, farthest.y)


# Convert room coordinates to block grid coordinates
func room_to_block(rx: int, ry: int) -> Vector2i:
	return Vector2i(rx * 2 + 1, ry * 2 + 1)


# Check if a block cell is walkable given held principles
func is_open(position: Vector2i, held_principles: Array) -> bool:
	if position not in cells:
		return false
	var value: int = cells[position]
	if value == 0:
		return true
	if value == 1:
		return false
	# Tagged wall: open if player holds the matching principle
	if position in cell_tags:
		for tag: StringName in cell_tags[position]:
			if tag in held_principles:
				return true
	return false


# BFS path to goal (for compass ability)
func path_to_goal(from: Vector2i, held_principles: Array) -> Array:
	var queue: Array = [from]
	var came_from: Dictionary = {from: from}
	while not queue.is_empty():
		var current: Vector2i = queue.pop_front()
		if current == goal:
			break
		for offset: Vector2i in [Vector2i(0,-1), Vector2i(0,1), Vector2i(-1,0), Vector2i(1,0)]:
			var next: Vector2i = current + offset
			if next not in came_from and is_open(next, held_principles):
				came_from[next] = current
				queue.append(next)
	if goal not in came_from:
		return []
	var path: Array = []
	var step: Vector2i = goal
	while step != from:
		path.append(step)
		step = came_from[step]
	path.reverse()
	return path


# Dead ends near a position (for pulse scan ability)
func nearby_dead_ends(position: Vector2i, reach: int = 8) -> Array:
	var found: Array = []
	for dead_end: Vector2i in dead_end_rooms:
		if absi(dead_end.x - position.x) + absi(dead_end.y - position.y) <= reach:
			found.append(dead_end)
	return found


# Get the corridor leading to a dead end (for full-corridor flash)
func dead_end_corridor(dead_end_block: Vector2i) -> Array:
	var corridor: Array = [dead_end_block]
	var current: Vector2i = dead_end_block
	# Walk backward from dead end until we hit a junction
	for _step: int in range(20):
		var open_neighbors: Array = []
		for offset: Vector2i in [Vector2i(0,-1), Vector2i(0,1), Vector2i(-1,0), Vector2i(1,0)]:
			var next: Vector2i = current + offset
			if next in cells and cells[next] == 0 and next not in corridor:
				open_neighbors.append(next)
		if open_neighbors.size() == 0:
			break
		# Also check the wall cell we'd pass through
		if open_neighbors.size() == 1:
			corridor.append(open_neighbors[0])
			# Check the room beyond
			var beyond: Vector2i = open_neighbors[0] + (open_neighbors[0] - current)
			if beyond in cells and cells[beyond] == 0:
				# Count how many open connections this room has
				var connections: int = 0
				for off2: Vector2i in [Vector2i(0,-2), Vector2i(0,2), Vector2i(-2,0), Vector2i(2,0)]:
					var check: Vector2i = beyond + off2
					if check in cells and cells[check] == 0:
						connections += 1
					var wall_check: Vector2i = beyond + off2 / 2
					if wall_check in cells and cells[wall_check] == 0:
						connections += 1
				corridor.append(beyond)
				if connections > 2:
					break  # Hit a junction, stop
				current = beyond
			else:
				break
		else:
			break
	return corridor
