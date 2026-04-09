extends Node

var all_principles: Array = []
var held: Array = []
var held_ids: Array = []
var dropped: Array = []
var level: int = 1
var total_levels: int = 5
var thresholds_crossed: int = 0
var max_held: int = 4

const OFFER_COUNT: int = 6
const DROP_COUNT: int = 1

var levels: Array = [
	{"width": 7, "height": 7, "picks": 4, "thresholds": 4, "shortcut_chance": 0.2},
	{"width": 9, "height": 9, "picks": 3, "thresholds": 4, "shortcut_chance": 0.25},
	{"width": 11, "height": 11, "picks": 3, "thresholds": 6, "shortcut_chance": 0.3},
	{"width": 13, "height": 13, "picks": 2, "thresholds": 6, "shortcut_chance": 0.3},
	{"width": 15, "height": 15, "picks": 1, "thresholds": 8, "shortcut_chance": 0.35},
]


func _ready() -> void:
	_create_principles()


func current_config() -> Dictionary:
	return levels[clampi(level - 1, 0, levels.size() - 1)]


func reset_level() -> void:
	held.clear()
	held_ids.clear()
	dropped.clear()
	thresholds_crossed = 0
	max_held = current_config()["picks"]
	for p: Principle in all_principles:
		p.refill()


func reset_game() -> void:
	level = 1
	reset_level()


func pick(principle: Principle) -> void:
	if principle not in held and held.size() < max_held:
		held.append(principle)
		principle.refill()
		_sync()
		MazeEvents.principles_changed.emit(held_ids)


func drop(principle: Principle) -> void:
	if principle in held:
		held.erase(principle)
		dropped.append(principle)
		_sync()
		MazeEvents.principle_dropped.emit(principle)
		MazeEvents.principles_changed.emit(held_ids)


func cross_threshold() -> void:
	thresholds_crossed += 1
	max_held -= DROP_COUNT
	MazeEvents.threshold_reached.emit(thresholds_crossed)


func find_principle(id: StringName) -> Principle:
	for p in all_principles:
		if p.id == id:
			return p
	return null


func spend_charge(id: StringName) -> bool:
	var p: Principle = find_principle(id)
	if p == null or p not in held or p.charges <= 0:
		return false
	p.charges -= 1
	MazeEvents.charges_changed.emit(id, p.charges)
	return true


func add_charge(id: StringName) -> void:
	var p: Principle = find_principle(id)
	if p and p in held:
		p.charges = mini(p.charges + 1, p.max_charges)
		MazeEvents.charges_changed.emit(id, p.charges)


func _sync() -> void:
	held_ids.clear()
	for p in held:
		held_ids.append(p.id)


func _create_principles() -> void:
	var data: Array = [
		{
			"id": &"harm_reduction", "name": "Harm Reduction",
			"description": "Minimize suffering wherever possible.",
			"color": Color(0.85, 0.25, 0.25),
			"loss_message": "You set down the weight of others' pain. The maze shifts.",
			"ability_name": "Pulse Scan", "ability_hint": "Reveal dead-end corridors nearby",
			"max_charges": 3,
		},
		{
			"id": &"autonomy", "name": "Autonomy",
			"description": "Respect each person's right to choose for themselves.",
			"color": Color(0.25, 0.65, 0.85),
			"loss_message": "Freedom slips from your vocabulary. New walls appear.",
			"ability_name": "Phase Walk", "ability_hint": "Pass through one wall",
			"max_charges": 2,
		},
		{
			"id": &"fairness", "name": "Fairness",
			"description": "Distribute costs and benefits equitably.",
			"color": Color(0.95, 0.75, 0.2),
			"loss_message": "The scales dissolve. Some paths you trusted are gone.",
			"ability_name": "Swap Blocks", "ability_hint": "Destroy an adjacent wall",
			"max_charges": 2,
		},
		{
			"id": &"utility", "name": "Utility",
			"description": "Maximize the total good across all affected parties.",
			"color": Color(0.3, 0.8, 0.4),
			"loss_message": "The calculus goes quiet. Efficiency was a kind of sight.",
			"ability_name": "Compass", "ability_hint": "Flash shortest path to goal",
			"max_charges": 3,
		},
		{
			"id": &"loyalty", "name": "Loyalty",
			"description": "Honor bonds and commitments to those close to you.",
			"color": Color(0.7, 0.4, 0.85),
			"loss_message": "Bonds loosen. The maze no longer remembers your allegiances.",
			"ability_name": "Breadcrumbs", "ability_hint": "Toggle visited path markers",
			"max_charges": 99,
		},
		{
			"id": &"care", "name": "Care",
			"description": "Attend to vulnerability and respond to need.",
			"color": Color(0.95, 0.55, 0.65),
			"loss_message": "Tenderness folds inward. Certain doors won't answer you now.",
			"ability_name": "Restore", "ability_hint": "Recharge all other abilities by 1",
			"max_charges": 2,
		},
	]

	for d in data:
		var p: Principle = Principle.new()
		p.id = d["id"]
		p.name = d["name"]
		p.description = d["description"]
		p.color = d["color"]
		p.loss_message = d["loss_message"]
		p.ability_name = d["ability_name"]
		p.ability_hint = d["ability_hint"]
		p.max_charges = d["max_charges"]
		p.charges = p.max_charges
		all_principles.append(p)
