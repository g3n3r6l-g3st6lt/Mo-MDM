extends CanvasLayer

var abilities_row: HBoxContainer
var level_text: Label
var feedback_text: Label
var loss_dimmer: ColorRect
var loss_message: Label


func _ready() -> void:
	layer = 10

	var bar: PanelContainer = PanelContainer.new()
	bar.set_anchors_preset(Control.PRESET_TOP_WIDE)
	bar.custom_minimum_size = Vector2(0, 70)
	var bar_style: StyleBoxFlat = StyleBoxFlat.new()
	bar_style.bg_color = Color(0.05, 0.05, 0.08, 0.85)
	bar.add_theme_stylebox_override("panel", bar_style)
	add_child(bar)

	var padding: MarginContainer = MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		padding.add_theme_constant_override("margin_" + side, 10)
	bar.add_child(padding)

	var rows: VBoxContainer = VBoxContainer.new()
	rows.add_theme_constant_override("separation", 4)
	padding.add_child(rows)

	var top_row: HBoxContainer = HBoxContainer.new()
	top_row.add_theme_constant_override("separation", 16)
	rows.add_child(top_row)

	level_text = Label.new()
	level_text.text = "Level 1"
	level_text.add_theme_color_override("font_color", Color(0.7, 0.7, 0.75))
	level_text.add_theme_font_size_override("font_size", 13)
	top_row.add_child(level_text)

	top_row.add_child(VSeparator.new())

	abilities_row = HBoxContainer.new()
	abilities_row.add_theme_constant_override("separation", 14)
	top_row.add_child(abilities_row)

	feedback_text = Label.new()
	feedback_text.add_theme_font_size_override("font_size", 11)
	feedback_text.modulate.a = 0.0
	rows.add_child(feedback_text)

	loss_dimmer = ColorRect.new()
	loss_dimmer.set_anchors_preset(Control.PRESET_FULL_RECT)
	loss_dimmer.color = Color(0, 0, 0, 0)
	loss_dimmer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(loss_dimmer)

	loss_message = Label.new()
	loss_message.set_anchors_preset(Control.PRESET_CENTER)
	loss_message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	loss_message.add_theme_color_override("font_color", Color(0.9, 0.85, 0.7))
	loss_message.add_theme_font_size_override("font_size", 18)
	loss_message.modulate.a = 0.0
	loss_dimmer.add_child(loss_message)

	MazeEvents.principles_changed.connect(func(_ids: Array): _refresh_abilities())
	MazeEvents.charges_changed.connect(func(_id: StringName, _c: int): _refresh_abilities())
	MazeEvents.principle_dropped.connect(_show_loss)
	MazeEvents.ability_used.connect(_show_ability_feedback)
	MazeEvents.ability_failed.connect(func(reason: String): _flash_feedback(reason, Color(0.6, 0.4, 0.4)))


func set_level(number: int) -> void:
	level_text.text = "Level %d" % number


func _refresh_abilities() -> void:
	for child in abilities_row.get_children():
		child.queue_free()

	var slot: int = 0
	for p: Principle in GameState.held:
		slot += 1
		var row: HBoxContainer = HBoxContainer.new()
		row.add_theme_constant_override("separation", 3)

		var dot: ColorRect = ColorRect.new()
		dot.custom_minimum_size = Vector2(10, 10)
		dot.color = p.color
		row.add_child(dot)

		var text: Label = Label.new()
		text.text = "%s [%d] (%d)" % [p.ability_name, slot, p.charges]
		text.add_theme_color_override("font_color", p.color.lightened(0.2))
		text.add_theme_font_size_override("font_size", 11)
		row.add_child(text)

		abilities_row.add_child(row)


func _show_loss(principle: Principle) -> void:
	loss_message.text = principle.loss_message
	var animation: Tween = create_tween()
	animation.tween_property(loss_dimmer, "color:a", 0.6, 0.5)
	animation.parallel().tween_property(loss_message, "modulate:a", 1.0, 0.8)
	animation.tween_interval(2.5)
	animation.tween_property(loss_message, "modulate:a", 0.0, 1.0)
	animation.parallel().tween_property(loss_dimmer, "color:a", 0.0, 1.2)


func _show_ability_feedback(principle_id: StringName) -> void:
	var p: Principle = GameState.find_principle(principle_id)
	if p:
		_flash_feedback(p.ability_name + " activated", p.color)


func _flash_feedback(text: String, color: Color) -> void:
	feedback_text.text = text
	feedback_text.add_theme_color_override("font_color", color)
	var animation: Tween = create_tween()
	animation.tween_property(feedback_text, "modulate:a", 1.0, 0.15)
	animation.tween_interval(1.5)
	animation.tween_property(feedback_text, "modulate:a", 0.0, 0.8)
