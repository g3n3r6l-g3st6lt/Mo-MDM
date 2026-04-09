extends CanvasLayer

var overlay: ColorRect
var content: VBoxContainer


func _ready() -> void:
	layer = 25
	visible = false
	MazeEvents.reached_goal.connect(_show)
	_build()


func _build() -> void:
	overlay = ColorRect.new()
	overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	overlay.color = Color(0.02, 0.02, 0.04, 0.0)
	add_child(overlay)

	var center: CenterContainer = CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	overlay.add_child(center)

	content = VBoxContainer.new()
	content.add_theme_constant_override("separation", 16)
	content.custom_minimum_size = Vector2(600, 0)
	content.modulate.a = 0.0
	center.add_child(content)


func _show() -> void:
	for child: Node in content.get_children():
		child.queue_free()

	var final_level: bool = GameState.level >= GameState.total_levels

	_add_label("You arrived." if final_level else "Level %d Complete" % GameState.level, 26, Color(0.9, 0.88, 0.82))
	_add_label("What you carried:", 14, Color(0.6, 0.6, 0.65))

	for p: Principle in GameState.held:
		_add_label("%s (%s)" % [p.name, p.ability_name], 13, p.color.lightened(0.2))

	if not GameState.dropped.is_empty():
		_add_spacer(8)
		_add_label("What you set down:", 14, Color(0.45, 0.45, 0.5))
		for p: Principle in GameState.dropped:
			_add_label(p.name + " — \"" + p.loss_message + "\"", 11, p.color.darkened(0.3))

	_add_spacer(16)

	if final_level:
		_add_label("The maze is always solvable. The question was what it cost.", 14, Color(0.5, 0.5, 0.55))
		_add_button("Return to Menu", func(): visible = false; MazeEvents.back_to_menu.emit())
	else:
		_add_button("Continue to Level %d" % (GameState.level + 1), func(): visible = false; MazeEvents.next_level.emit())

	visible = true
	var fade: Tween = create_tween()
	fade.tween_property(overlay, "color:a", 0.92, 1.2)
	fade.parallel().tween_property(content, "modulate:a", 1.0, 1.8).set_delay(0.4)


func _add_label(text: String, size: int, color: Color) -> void:
	var label: Label = Label.new()
	label.text = text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD
	label.custom_minimum_size = Vector2(500, 0)
	content.add_child(label)

func _add_spacer(height: int) -> void:
	var spacer: Control = Control.new()
	spacer.custom_minimum_size = Vector2(0, height)
	content.add_child(spacer)

func _add_button(text: String, action: Callable) -> void:
	var center: CenterContainer = CenterContainer.new()
	var button: Button = Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(240, 40)
	button.pressed.connect(action)
	center.add_child(button)
	content.add_child(center)
