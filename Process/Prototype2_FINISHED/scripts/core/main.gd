extends Node2D

var renderer: Node2D
var player: Node2D
var camera: Camera2D
var hud: CanvasLayer
var picker: CanvasLayer
var end_screen: CanvasLayer
var menu: CanvasLayer

var maze: MazeGenerator


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.03, 0.03, 0.06))
	_register_ability_keys()
	_create_nodes()

	menu.show_menu()
	menu.start_pressed.connect(_start_game)
	MazeEvents.next_level.connect(_next_level)
	MazeEvents.back_to_menu.connect(_return_to_menu)


func _register_ability_keys() -> void:
	for i: int in range(1, 7):
		var action: String = "perk_%d" % i
		if not InputMap.has_action(action):
			InputMap.add_action(action)
			var key: InputEventKey = InputEventKey.new()
			key.physical_keycode = KEY_0 + i
			InputMap.action_add_event(action, key)


func _create_nodes() -> void:
	renderer = Node2D.new()
	renderer.set_script(load("res://scripts/maze/maze_renderer.gd"))
	add_child(renderer)

	player = Node2D.new()
	player.set_script(load("res://scripts/player/player.gd"))
	add_child(player)

	camera = Camera2D.new()
	camera.set_script(load("res://scripts/player/isometric_camera.gd"))
	add_child(camera)

	hud = CanvasLayer.new()
	hud.set_script(load("res://scripts/ui/hud.gd"))
	add_child(hud)

	picker = CanvasLayer.new()
	picker.set_script(load("res://scripts/ui/principle_selection_ui.gd"))
	add_child(picker)

	end_screen = CanvasLayer.new()
	end_screen.set_script(load("res://scripts/ui/end_screen.gd"))
	add_child(end_screen)

	menu = CanvasLayer.new()
	menu.set_script(load("res://scripts/ui/main_menu.gd"))
	add_child(menu)


func _start_game() -> void:
	GameState.reset_game()
	_begin_level()


func _next_level() -> void:
	GameState.level += 1
	GameState.reset_level()
	_begin_level()


func _return_to_menu() -> void:
	player.visible = false
	renderer.visible = false
	menu.show_menu()


func _begin_level() -> void:
	player.visible = true
	renderer.visible = true
	hud.set_level(GameState.level)

	PrincipleManager.done.connect(_on_picks_confirmed, CONNECT_ONE_SHOT)
	PrincipleManager.show_pick_screen()


func _on_picks_confirmed() -> void:
	var config: Dictionary = GameState.current_config()
	maze = MazeGenerator.new(config["width"], config["height"])
	maze.build(GameState.held_ids, config)

	renderer.draw_maze(maze)
	player.setup(maze, renderer)
	player.set_process(true)
	camera.follow(player)
