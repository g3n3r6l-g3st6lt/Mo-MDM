extends CanvasLayer

signal start_pressed()

var overlay: ColorRect
var tutorial_panel: ColorRect


func _ready() -> void:
	layer = 30
	_build_menu()


func _build_menu() -> void:
	overlay = ColorRect.new()
	overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	overlay.color = Color(0.03, 0.03, 0.06, 0.98)
	add_child(overlay)

	var center: CenterContainer = CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	overlay.add_child(center)

	var column: VBoxContainer = VBoxContainer.new()
	column.add_theme_constant_override("separation", 20)
	column.custom_minimum_size = Vector2(500, 0)
	center.add_child(column)

	_label(column, "The Final Problem", 36, Color(0.9, 0.85, 0.75))
	_label(column, "A maze about the cost of simplification", 14, Color(0.5, 0.5, 0.55))
	_spacer(column, 20)
	_label(column, "Ready when you are..", 13, Color(0.55, 0.55, 0.6))
	_spacer(column, 10)
	_centered_button(column, "Start Game", Vector2(220, 48), _on_start)
	_centered_button(column, "How to Play", Vector2(220, 40), _on_tutorial)

	_build_tutorial()


func _build_tutorial() -> void:
	tutorial_panel = ColorRect.new()
	tutorial_panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	tutorial_panel.color = Color(0.03, 0.03, 0.06, 0.98)
	tutorial_panel.visible = false
	add_child(tutorial_panel)

	var scroll: ScrollContainer = ScrollContainer.new()
	scroll.set_anchors_preset(Control.PRESET_FULL_RECT)
	tutorial_panel.add_child(scroll)

	var center: CenterContainer = CenterContainer.new()
	center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.custom_minimum_size = Vector2(700, 800)
	scroll.add_child(center)

	var column: VBoxContainer = VBoxContainer.new()
	column.add_theme_constant_override("separation", 14)
	column.custom_minimum_size = Vector2(600, 0)
	center.add_child(column)

	_label(column, "HOW TO PLAY", 24, Color(0.9, 0.85, 0.75))

	var sections: Array = [
		["Movement", "WASD to move. Your goal is to move from the green start marker to the gold marker."],
		["Principles", "At the start of each level, choose moral principles to carry. Each one reveals hidden paths (colored walls matching that principle) and grants a unique ability with limited charges."],
		["Abilities (Number Keys)", "Press 1-4 (based on position in your held principles) to activate:\n\n  Harm Reduction: Pulse Scan — highlights entire dead-end corridors in red\n  Autonomy: Phase Walk — pass through one wall (move into it while active)\n  Fairness: Break Wall — destroys an adjacent wall block\n  Utility: Compass — briefly shows the shortest path to the goal\n  Loyalty: Breadcrumbs — toggles visibility of your visited path\n  Care: Restore — recharges all other abilities by 1 charge"],
		["Thresholds", "Purple markers at maze intersections are threshold points. When you step on one, you must drop a principle. The maze blocks some paths AND you lose the principle's perk permanently."],
		["Levels", "Five levels of increasing size and difficulty. Mazes get larger, thresholds become more frequent, and later levels reduce your starting perks."],
	]

	for section in sections:
		_label(column, section[0], 16, Color(0.8, 0.75, 0.65))
		var body: Label = Label.new()
		body.text = section[1]
		body.autowrap_mode = TextServer.AUTOWRAP_WORD
		body.add_theme_font_size_override("font_size", 12)
		body.add_theme_color_override("font_color", Color(0.55, 0.55, 0.6))
		body.custom_minimum_size = Vector2(560, 0)
		column.add_child(body)

	_spacer(column, 10)
	_centered_button(column, "Back", Vector2(160, 40), func(): tutorial_panel.visible = false)


func _on_start() -> void:
	visible = false
	start_pressed.emit()

func _on_tutorial() -> void:
	tutorial_panel.visible = true

func show_menu() -> void:
	visible = true
	tutorial_panel.visible = false


# Helpers
func _label(parent: VBoxContainer, text: String, size: int, color: Color) -> void:
	var l: Label = Label.new()
	l.text = text
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	l.autowrap_mode = TextServer.AUTOWRAP_WORD
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.custom_minimum_size = Vector2(460, 0)
	parent.add_child(l)

func _spacer(parent: VBoxContainer, height: int) -> void:
	var s: Control = Control.new()
	s.custom_minimum_size = Vector2(0, height)
	parent.add_child(s)

func _centered_button(parent: VBoxContainer, text: String, size: Vector2, action: Callable) -> void:
	var c: CenterContainer = CenterContainer.new()
	var b: Button = Button.new()
	b.text = text
	b.custom_minimum_size = size
	b.pressed.connect(action)
	c.add_child(b)
	parent.add_child(c)
