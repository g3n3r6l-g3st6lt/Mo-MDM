extends Node2D

const TILE_W: float = 48.0
const TILE_H: float = 24.0
const CUBE_H: float = 30.0

var maze: MazeGenerator = null

var floor_layer: Node2D
var cube_layer: Node2D
var marker_layer: Node2D
var effects_layer: Node2D
var trail_layer: Node2D

var cubes: Dictionary = {}  # position -> Node2D
var trail_visible: bool = false


func _ready() -> void:
	MazeEvents.principles_changed.connect(func(_ids: Array): refresh_walls())
	MazeEvents.maze_needs_refresh.connect(refresh_walls)
	MazeEvents.principle_dropped.connect(_flash_new_walls)

	floor_layer = Node2D.new()
	add_child(floor_layer)

	cube_layer = Node2D.new()
	add_child(cube_layer)

	marker_layer = Node2D.new()
	marker_layer.z_index = 50
	add_child(marker_layer)

	effects_layer = Node2D.new()
	effects_layer.z_index = 40
	add_child(effects_layer)

	trail_layer = Node2D.new()
	trail_layer.z_index = 30
	trail_layer.visible = false
	add_child(trail_layer)


func draw_maze(generator: MazeGenerator) -> void:
	maze = generator
	_clear_everything()
	_draw_floors()
	_draw_cubes()
	_draw_markers()
	refresh_walls()


func to_screen(position: Vector2i) -> Vector2:
	return Vector2(
		(position.x - position.y) * TILE_W * 0.5,
		(position.x + position.y) * TILE_H * 0.5
	)


# --- Drawing ---

func _draw_floors() -> void:
	for position: Vector2i in maze.cells:
		var value: int = maze.cells[position]
		if value == 1:
			continue

		var screen: Vector2 = to_screen(position)

		var tile: Polygon2D = Polygon2D.new()
		tile.polygon = _diamond()
		tile.color = Color(0.12, 0.12, 0.15, 0.35)
		tile.position = screen
		floor_layer.add_child(tile)

		var border: Line2D = Line2D.new()
		border.points = PackedVector2Array([
			Vector2(0, -TILE_H * 0.5), Vector2(TILE_W * 0.5, 0),
			Vector2(0, TILE_H * 0.5), Vector2(-TILE_W * 0.5, 0),
			Vector2(0, -TILE_H * 0.5),
		])
		border.width = 1.0
		border.default_color = Color(0.25, 0.25, 0.3, 0.3)
		border.position = screen
		floor_layer.add_child(border)

		# Floor under tagged walls (they might disappear)
		if value == 2:
			var hidden_floor: Polygon2D = Polygon2D.new()
			hidden_floor.polygon = _diamond()
			hidden_floor.color = Color(0.12, 0.12, 0.15, 0.35)
			hidden_floor.position = screen
			floor_layer.add_child(hidden_floor)


func _draw_cubes() -> void:
	var wall_positions: Array = []
	for position: Vector2i in maze.cells:
		if maze.cells[position] >= 1:
			wall_positions.append(position)

	wall_positions.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
		return (a.x + a.y) < (b.x + b.y)
	)

	for position: Vector2i in wall_positions:
		var screen: Vector2 = to_screen(position)
		var is_tagged: bool = (maze.cells[position] == 2)
		var cube: Node2D = _build_cube(screen, position, is_tagged)
		cube_layer.add_child(cube)
		cubes[position] = cube


func _build_cube(screen: Vector2, position: Vector2i, is_tagged: bool) -> Node2D:
	var node: Node2D = Node2D.new()
	node.position = screen

	var hw: float = TILE_W * 0.5
	var hh: float = TILE_H * 0.5

	var base_color: Color
	if is_tagged and position in maze.cell_tags:
		var principle: Principle = GameState.find_principle(maze.cell_tags[position][0])
		base_color = principle.color.darkened(0.2) if principle else Color(0.5, 0.12, 0.12)
	else:
		base_color = Color(0.4, 0.06, 0.06)

	# Top face (brightest)
	var top: Polygon2D = Polygon2D.new()
	top.polygon = PackedVector2Array([
		Vector2(0, -hh - CUBE_H), Vector2(hw, -CUBE_H),
		Vector2(0, hh - CUBE_H), Vector2(-hw, -CUBE_H),
	])
	top.color = Color(base_color.r + 0.12, base_color.g + 0.06, base_color.b + 0.06, 0.7)
	node.add_child(top)

	# Left face (medium)
	var left_face: Polygon2D = Polygon2D.new()
	left_face.polygon = PackedVector2Array([
		Vector2(-hw, -CUBE_H), Vector2(0, hh - CUBE_H),
		Vector2(0, hh), Vector2(-hw, 0),
	])
	left_face.color = Color(base_color.r, base_color.g, base_color.b, 0.65)
	node.add_child(left_face)

	# Right face (darkest)
	var right_face: Polygon2D = Polygon2D.new()
	right_face.polygon = PackedVector2Array([
		Vector2(hw, -CUBE_H), Vector2(hw, 0),
		Vector2(0, hh), Vector2(0, hh - CUBE_H),
	])
	right_face.color = Color(base_color.r - 0.06, base_color.g - 0.02, base_color.b - 0.02, 0.6)
	node.add_child(right_face)

	node.set_meta("tagged", is_tagged)
	return node


func _draw_markers() -> void:
	# Start marker
	var start_screen: Vector2 = to_screen(maze.room_to_block(0, 0))
	marker_layer.add_child(_make_marker(start_screen, Color(0.3, 0.85, 0.4, 0.85), 7.0))

	# Goal marker (pulsing)
	var goal_screen: Vector2 = to_screen(maze.goal)
	var goal_marker: Node2D = _make_marker(goal_screen, Color(1.0, 0.85, 0.15, 0.95), 8.0)
	marker_layer.add_child(goal_marker)
	var pulse: Tween = create_tween().set_loops()
	pulse.tween_property(goal_marker, "scale", Vector2(1.4, 1.4), 0.7).set_trans(Tween.TRANS_SINE)
	pulse.tween_property(goal_marker, "scale", Vector2(0.8, 0.8), 0.7).set_trans(Tween.TRANS_SINE)

	# Threshold markers
	for spot: Vector2i in maze.threshold_spots:
		marker_layer.add_child(_make_marker(to_screen(spot), Color(0.7, 0.4, 0.9, 0.75), 5.0))


func _make_marker(screen: Vector2, color: Color, size: float) -> Node2D:
	var node: Node2D = Node2D.new()
	node.position = screen + Vector2(0, -CUBE_H * 0.5)
	var shape: Polygon2D = Polygon2D.new()
	shape.polygon = PackedVector2Array([
		Vector2(0, -size), Vector2(size, 0),
		Vector2(0, size), Vector2(-size, 0),
	])
	shape.color = color
	node.add_child(shape)
	return node


# --- Visibility ---

func refresh_walls() -> void:
	var held: Array = GameState.held_ids
	for position: Vector2i in cubes:
		var cube: Node2D = cubes[position]
		if not cube.get_meta("tagged", false):
			cube.visible = true
		else:
			cube.visible = not maze.is_open(position, held)


func _flash_new_walls(principle: Principle) -> void:
	# When a principle is dropped, walls that reappear flash in its color
	for position: Vector2i in cubes:
		var cube: Node2D = cubes[position]
		if not cube.get_meta("tagged", false):
			continue
		if position not in maze.cell_tags:
			continue
		if principle.id in maze.cell_tags[position] and cube.visible:
			cube.modulate = Color(1.5, 1.2, 1.2, 1.0)
			var fade: Tween = create_tween()
			fade.tween_property(cube, "modulate", Color(1, 1, 1, 1), 1.5)


# --- Ability visuals ---

# Flash entire dead-end corridors (not just the end cell)
func highlight_dead_ends(dead_end_positions: Array) -> void:
	for dead_end: Vector2i in dead_end_positions:
		var corridor: Array = maze.dead_end_corridor(dead_end)
		for cell: Vector2i in corridor:
			var screen: Vector2 = to_screen(cell)
			var warning: Polygon2D = Polygon2D.new()
			warning.polygon = _diamond()
			warning.color = Color(0.85, 0.25, 0.25, 0.5)
			warning.position = screen
			effects_layer.add_child(warning)
			var fade: Tween = create_tween()
			fade.tween_property(warning, "color:a", 0.0, 3.0)
			fade.tween_callback(warning.queue_free)


func flash_path(path: Array) -> void:
	var delay: float = 0.0
	for position: Vector2i in path:
		var dot: Polygon2D = Polygon2D.new()
		dot.polygon = PackedVector2Array([
			Vector2(0, -4), Vector2(4, 0), Vector2(0, 4), Vector2(-4, 0),
		])
		dot.color = Color(0.3, 0.8, 0.4, 0.0)
		dot.position = to_screen(position)
		effects_layer.add_child(dot)
		var flash: Tween = create_tween()
		flash.tween_property(dot, "color:a", 0.7, 0.1).set_delay(delay)
		flash.tween_property(dot, "color:a", 0.0, 2.0)
		flash.tween_callback(dot.queue_free)
		delay += 0.02


func show_trail(visited: Dictionary) -> void:
	trail_visible = not trail_visible
	if not trail_visible:
		trail_layer.visible = false
		return
	for child: Node in trail_layer.get_children():
		child.queue_free()
	for position: Vector2i in visited:
		var dot: Polygon2D = Polygon2D.new()
		dot.polygon = PackedVector2Array([
			Vector2(0, -3), Vector2(3, 0), Vector2(0, 3), Vector2(-3, 0),
		])
		dot.color = Color(0.7, 0.4, 0.85, 0.4)
		dot.position = to_screen(position)
		trail_layer.add_child(dot)
	trail_layer.visible = true


func destroy_wall(position: Vector2i) -> void:
	if position in cubes:
		cubes[position].queue_free()
		cubes.erase(position)

func create_floor(position: Vector2i) -> void:
	var screen: Vector2 = to_screen(position)
	var tile: Polygon2D = Polygon2D.new()
	tile.polygon = _diamond()
	tile.color = Color(0.12, 0.12, 0.15, 0.35)
	tile.position = screen
	floor_layer.add_child(tile)
	# Flash effect
	var glow: Polygon2D = Polygon2D.new()
	glow.polygon = _diamond()
	glow.color = Color(0.95, 0.75, 0.2, 0.6)
	glow.position = screen
	effects_layer.add_child(glow)
	var fade: Tween = create_tween()
	fade.tween_property(glow, "color:a", 0.0, 1.0)
	fade.tween_callback(glow.queue_free)


func _diamond() -> PackedVector2Array:
	return PackedVector2Array([
		Vector2(0, -TILE_H * 0.5), Vector2(TILE_W * 0.5, 0),
		Vector2(0, TILE_H * 0.5), Vector2(-TILE_W * 0.5, 0),
	])


func _clear_everything() -> void:
	for layer in [floor_layer, cube_layer, marker_layer, effects_layer, trail_layer]:
		for child: Node in layer.get_children():
			child.queue_free()
	cubes.clear()
	trail_visible = false
	trail_layer.visible = false
