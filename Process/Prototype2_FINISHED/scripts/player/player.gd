extends Node2D

var position_on_grid: Vector2i = Vector2i.ZERO
var target_screen: Vector2 = Vector2.ZERO
var moving: bool = false
var maze: MazeGenerator = null
var renderer: Node2D = null

var cooldown: float = 0.0
const COOLDOWN_TIME: float = 0.12

var phasing: bool = false
var visited: Dictionary = {}

var body: Polygon2D
var glow: Polygon2D


func _ready() -> void:
	_make_sprite()
	z_index = 100


func _make_sprite() -> void:
	var lift: float = -22.0

	glow = Polygon2D.new()
	glow.polygon = PackedVector2Array([
		Vector2(0, -14 + lift), Vector2(12, 0 + lift),
		Vector2(0, 10 + lift), Vector2(-12, 0 + lift),
	])
	glow.color = Color(0.4, 0.6, 1.0, 0.3)
	glow.z_index = -1
	add_child(glow)

	body = Polygon2D.new()
	body.polygon = PackedVector2Array([
		Vector2(0, -11 + lift), Vector2(9, 0 + lift),
		Vector2(0, 7 + lift), Vector2(-9, 0 + lift),
	])
	body.color = Color(0.7, 0.85, 1.0)
	add_child(body)

	var pulse: Tween = create_tween().set_loops()
	pulse.tween_property(glow, "modulate:a", 0.5, 1.0).set_trans(Tween.TRANS_SINE)
	pulse.tween_property(glow, "modulate:a", 1.0, 1.0).set_trans(Tween.TRANS_SINE)


func setup(generator: MazeGenerator, maze_renderer: Node2D) -> void:
	maze = generator
	renderer = maze_renderer
	position_on_grid = maze.room_to_block(0, 0)
	position = renderer.to_screen(position_on_grid)
	target_screen = position
	visited.clear()
	visited[position_on_grid] = true
	phasing = false


func _process(delta: float) -> void:
	if cooldown > 0.0:
		cooldown -= delta
	if not moving:
		_check_movement()
		_check_abilities()
	_slide_to_target(delta)


func _check_movement() -> void:
	if cooldown > 0.0:
		return

	var direction: Vector2i = Vector2i.ZERO
	if Input.is_action_pressed("move_up"):
		direction = Vector2i(0, -1)
	elif Input.is_action_pressed("move_down"):
		direction = Vector2i(0, 1)
	elif Input.is_action_pressed("move_left"):
		direction = Vector2i(-1, 0)
	elif Input.is_action_pressed("move_right"):
		direction = Vector2i(1, 0)

	if direction == Vector2i.ZERO:
		return

	var destination: Vector2i = position_on_grid + direction

	# Phase walk: pass through one wall
	if phasing:
		if destination in maze.cells and maze.cells[destination] >= 1:
			var beyond: Vector2i = destination + direction
			if beyond in maze.cells and maze.cells[beyond] == 0:
				_move_to(beyond)
				phasing = false
				body.color = Color(0.7, 0.85, 1.0)
				return
		phasing = false
		body.color = Color(0.7, 0.85, 1.0)

	if not maze.is_open(destination, GameState.held_ids):
		_bump(direction)
		cooldown = COOLDOWN_TIME
		return

	_move_to(destination)


func _move_to(destination: Vector2i) -> void:
	position_on_grid = destination
	target_screen = renderer.to_screen(position_on_grid)
	moving = true
	cooldown = COOLDOWN_TIME
	visited[position_on_grid] = true
	MazeEvents.player_moved.emit(position_on_grid)

	# Win check
	if position_on_grid == maze.goal:
		set_process(false)
		MazeEvents.reached_goal.emit()
		return

	# Threshold check
	if position_on_grid in maze.threshold_spots:
		_handle_threshold()


func _check_abilities() -> void:
	for i: int in range(GameState.held.size()):
		var key: String = "perk_%d" % (i + 1)
		if Input.is_action_just_pressed(key):
			_use_ability(GameState.held[i])
			return


func _use_ability(principle: Principle) -> void:
	if principle.charges <= 0:
		MazeEvents.ability_failed.emit("No charges left for " + principle.ability_name)
		return

	match principle.id:
		&"harm_reduction": _ability_pulse_scan(principle)
		&"autonomy": _ability_phase_walk(principle)
		&"fairness": _ability_break_wall(principle)
		&"utility": _ability_compass(principle)
		&"loyalty": _ability_breadcrumbs(principle)
		&"care": _ability_restore(principle)


func _ability_pulse_scan(principle: Principle) -> void:
	if not GameState.spend_charge(principle.id):
		return
	MazeEvents.ability_used.emit(principle.id)
	var nearby: Array = maze.nearby_dead_ends(position_on_grid, 10)
	if nearby.is_empty():
		MazeEvents.ability_failed.emit("No dead ends nearby")
		GameState.add_charge(principle.id)
		return
	renderer.highlight_dead_ends(nearby)


func _ability_phase_walk(principle: Principle) -> void:
	if not GameState.spend_charge(principle.id):
		return
	MazeEvents.ability_used.emit(principle.id)
	phasing = true
	body.color = Color(0.3, 0.6, 1.0)


func _ability_break_wall(principle: Principle) -> void:
	if not GameState.spend_charge(principle.id):
		return
	MazeEvents.ability_used.emit(principle.id)
	for offset: Vector2i in [Vector2i(0,-1), Vector2i(0,1), Vector2i(-1,0), Vector2i(1,0)]:
		var wall: Vector2i = position_on_grid + offset
		if wall in maze.cells and maze.cells[wall] == 1:
			maze.cells[wall] = 0
			renderer.destroy_wall(wall)
			renderer.create_floor(wall)
			return
	MazeEvents.ability_failed.emit("No adjacent wall to break")
	GameState.add_charge(principle.id)


func _ability_compass(principle: Principle) -> void:
	if not GameState.spend_charge(principle.id):
		return
	MazeEvents.ability_used.emit(principle.id)
	var path: Array = maze.path_to_goal(position_on_grid, GameState.held_ids)
	if path.is_empty():
		MazeEvents.ability_failed.emit("No path found")
		GameState.add_charge(principle.id)
		return
	renderer.flash_path(path)


func _ability_breadcrumbs(principle: Principle) -> void:
	MazeEvents.ability_used.emit(principle.id)
	renderer.show_trail(visited)


func _ability_restore(principle: Principle) -> void:
	if not GameState.spend_charge(principle.id):
		return
	MazeEvents.ability_used.emit(principle.id)
	for p: Principle in GameState.held:
		if p.id != principle.id:
			GameState.add_charge(p.id)


func _slide_to_target(delta: float) -> void:
	if not moving:
		return
	position = position.lerp(target_screen, 10.0 * delta)
	if position.distance_to(target_screen) < 0.5:
		position = target_screen
		moving = false


func _bump(direction: Vector2i) -> void:
	var nudge: Vector2 = Vector2(direction.x * 3, direction.y * 3)
	var bounce: Tween = create_tween()
	bounce.tween_property(body, "position", nudge, 0.05)
	bounce.tween_property(body, "position", Vector2.ZERO, 0.08)


func _handle_threshold() -> void:
	set_process(false)
	await get_tree().create_timer(0.3).timeout
	PrincipleManager.show_drop_screen()
	await PrincipleManager.done
	maze.threshold_spots.erase(position_on_grid)
	set_process(true)
