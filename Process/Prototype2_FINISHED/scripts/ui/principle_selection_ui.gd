extends CanvasLayer

var overlay: ColorRect
var container: VBoxContainer
var title_text: Label
var subtitle_text: Label
var card_grid: GridContainer
var confirm_button: Button

var mode: String = "pick"
var chosen: Array = []
var needed: int = 4
var options: Array = []


func _ready() -> void:
	layer = 20
	visible = false
	PrincipleManager.pick_screen.connect(_show_pick)
	PrincipleManager.drop_screen.connect(_show_drop)
	_build()


func _build() -> void:
	overlay = ColorRect.new()
	overlay.set_anchors_preset(Control.PRESET_FULL_RECT)
	overlay.color = Color(0.03, 0.03, 0.06, 0.92)
	add_child(overlay)

	var scroll: ScrollContainer = ScrollContainer.new()
	scroll.set_anchors_preset(Control.PRESET_FULL_RECT)
	overlay.add_child(scroll)

	var center: CenterContainer = CenterContainer.new()
	center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	center.custom_minimum_size = Vector2(800, 600)
	scroll.add_child(center)

	container = VBoxContainer.new()
	container.add_theme_constant_override("separation", 16)
	container.custom_minimum_size = Vector2(750, 0)
	center.add_child(container)

	title_text = Label.new()
	title_text.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title_text.add_theme_font_size_override("font_size", 24)
	title_text.add_theme_color_override("font_color", Color(0.9, 0.88, 0.82))
	container.add_child(title_text)

	subtitle_text = Label.new()
	subtitle_text.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	subtitle_text.add_theme_font_size_override("font_size", 13)
	subtitle_text.add_theme_color_override("font_color", Color(0.55, 0.55, 0.6))
	subtitle_text.autowrap_mode = TextServer.AUTOWRAP_WORD
	container.add_child(subtitle_text)

	card_grid = GridContainer.new()
	card_grid.columns = 3
	card_grid.add_theme_constant_override("h_separation", 10)
	card_grid.add_theme_constant_override("v_separation", 10)
	container.add_child(card_grid)

	var button_row: CenterContainer = CenterContainer.new()
	confirm_button = Button.new()
	confirm_button.custom_minimum_size = Vector2(200, 44)
	confirm_button.disabled = true
	confirm_button.pressed.connect(_on_confirm)
	button_row.add_child(confirm_button)
	container.add_child(button_row)


func _show_pick(offered: Array, picks: int) -> void:
	mode = "pick"
	options = offered
	needed = picks
	chosen.clear()
	title_text.text = "Choose Your Principles"
	subtitle_text.text = "Select %d principles. Each grants a unique ability. Press its number key [1-%d] to activate." % [picks, picks]
	confirm_button.text = "Enter the Maze"
	confirm_button.disabled = true
	_fill_cards(offered)
	visible = true


func _show_drop(held: Array, drop_count: int) -> void:
	mode = "drop"
	options = held
	needed = drop_count
	chosen.clear()
	title_text.text = "The Maze Narrows"
	subtitle_text.text = "Release %d principle to continue. Its ability will be lost." % drop_count
	confirm_button.text = "Let Go"
	confirm_button.disabled = true
	_fill_cards(held)
	visible = true


func _fill_cards(principles: Array) -> void:
	for child in card_grid.get_children():
		child.queue_free()
	for p: Principle in principles:
		card_grid.add_child(_make_card(p))


func _make_card(principle: Principle) -> PanelContainer:
	var card: PanelContainer = PanelContainer.new()
	card.custom_minimum_size = Vector2(230, 150)

	var style: StyleBoxFlat = StyleBoxFlat.new()
	style.bg_color = Color(0.1, 0.1, 0.14)
	style.border_color = Color(0.2, 0.2, 0.25)
	style.set_border_width_all(2)
	style.set_corner_radius_all(6)
	style.set_content_margin_all(12)
	card.add_theme_stylebox_override("panel", style)

	var column: VBoxContainer = VBoxContainer.new()
	column.add_theme_constant_override("separation", 6)
	card.add_child(column)

	var header: HBoxContainer = HBoxContainer.new()
	header.add_theme_constant_override("separation", 8)
	column.add_child(header)

	var color_stripe: ColorRect = ColorRect.new()
	color_stripe.custom_minimum_size = Vector2(4, 20)
	color_stripe.color = principle.color
	header.add_child(color_stripe)

	var name_text: Label = Label.new()
	name_text.text = principle.name
	name_text.add_theme_font_size_override("font_size", 15)
	name_text.add_theme_color_override("font_color", principle.color.lightened(0.3))
	header.add_child(name_text)

	var description: Label = Label.new()
	description.text = principle.description
	description.autowrap_mode = TextServer.AUTOWRAP_WORD
	description.add_theme_font_size_override("font_size", 11)
	description.add_theme_color_override("font_color", Color(0.55, 0.55, 0.6))
	column.add_child(description)

	var ability_label: Label = Label.new()
	ability_label.text = "Ability: %s (%d charges)" % [principle.ability_name, principle.max_charges]
	ability_label.add_theme_font_size_override("font_size", 11)
	ability_label.add_theme_color_override("font_color", Color(0.7, 0.75, 0.5))
	column.add_child(ability_label)

	var ability_description: Label = Label.new()
	ability_description.text = principle.ability_hint
	ability_description.add_theme_font_size_override("font_size", 10)
	ability_description.add_theme_color_override("font_color", Color(0.5, 0.5, 0.45))
	column.add_child(ability_description)

	card.gui_input.connect(func(event: InputEvent):
		if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
			_toggle(principle, card, style)
	)
	return card


func _toggle(principle: Principle, _card: PanelContainer, style: StyleBoxFlat) -> void:
	if principle in chosen:
		chosen.erase(principle)
		style.border_color = Color(0.2, 0.2, 0.25)
		style.bg_color = Color(0.1, 0.1, 0.14)
	else:
		if chosen.size() >= needed:
			return
		chosen.append(principle)
		style.border_color = principle.color
		style.bg_color = principle.color.darkened(0.8)
	confirm_button.disabled = (chosen.size() != needed)


func _on_confirm() -> void:
	visible = false
	if mode == "pick":
		PrincipleManager.confirm_picks(chosen.duplicate())
	elif mode == "drop":
		PrincipleManager.confirm_drops(chosen.duplicate())
	chosen.clear()
