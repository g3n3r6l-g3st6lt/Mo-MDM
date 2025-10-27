bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G. (plus ChatGPT)",
    "version": (1, 2, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A Prim's maze-generator that explores efficiency vs. exploration. The generator is highly adjustable to your preferences, and you can even save a preset you liked!",
    "category": "Add Mesh",
}

import bpy, random, math, os
from mathutils import Vector
from collections import deque
from math import inf
from bpy.props import (
    IntProperty, FloatProperty, BoolProperty, FloatVectorProperty,
    PointerProperty, StringProperty, EnumProperty, CollectionProperty
)
from bpy.types import Operator, Panel, PropertyGroup, AddonPreferences

# ====== Runtime cache of the latest generated maze (navigator uses this) ======
LAST_MAZE_CACHE = None  # set by Generate operator

# =========================
# Core utilities
# =========================
def sit_on_ground(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    o_eval = obj.evaluated_get(dg)
    corners_world = [o_eval.matrix_world @ Vector(c) for c in o_eval.bound_box]
    min_z = min(v.z for v in corners_world)
    obj.location.z -= min_z

def ensure_solid_material(name, rgba=(1.0, 1.0, 1.0, 1.0)):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = rgba
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat

def get_maze_collection(name="maze"):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col

def clear_collection_objects(col):
    to_delete = list(col.objects)
    if not to_delete:
        return
    for ob in to_delete:
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        bpy.data.objects.remove(ob)

def link_exclusive(ob, target_col):
    if target_col not in ob.users_collection:
        target_col.objects.link(ob)
    for c in list(ob.users_collection):
        if c != target_col:
            c.objects.unlink(ob)

def select_only(objs):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        try: o.select_set(True)
        except: pass
    if objs:
        bpy.context.view_layer.objects.active = objs[0]

# =========================
# Maze generation & logic
# =========================
# Bitmap: True=wall, False=passage; size H=rows*2+1, W=cols*2+1
def prims_maze(rows, cols, rng):
    H, W = rows*2+1, cols*2+1
    grid = [[True for _ in range(W)] for _ in range(H)]
    sr, sc = rng.randrange(rows), rng.randrange(cols)
    cr, cc = sr*2+1, sc*2+1
    grid[cr][cc] = False
    frontiers = []
    def add_frontiers(r, c):
        for dr, dc in ((-2,0),(2,0),(0,-2),(0,2)):
            rr, cc = r+dr, c+dc
            if 1 <= rr < H-1 and 1 <= cc < W-1 and grid[rr][cc]:
                frontiers.append(((rr,cc), (r+dr//2, c+dc//2)))
    add_frontiers(cr, cc)
    while frontiers:
        i = rng.randrange(len(frontiers))
        (rr,cc), (br,bc) = frontiers.pop(i)
        if grid[rr][cc]:
            grid[br][bc] = False
            grid[rr][cc] = False
            add_frontiers(rr, cc)
    # entrance (left) & exit (right)
    start = end = None
    for r in range(1, H-1):
        if not grid[r][1]: grid[r][0] = False; start = (r,0); break
    for r in range(H-2, 0, -1):
        if not grid[r][W-2]: grid[r][W-1] = False; end = (r,W-1); break
    return grid, H, W, start, end

def is_border_cell(r, c, rows, cols):
    return r == 0 or c == 0 or r == rows-1 or c == cols-1

def passage_degree(grid, r, c):
    rows, cols = len(grid), len(grid[0])
    if grid[r][c]: return 0
    deg = 0
    for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr, cc = r+dr, c+dc
        if 0 <= rr < rows and 0 <= cc < cols and not grid[rr][cc]:
            deg += 1
    return deg

def count_passages_and_deadends(grid):
    rows, cols = len(grid), len(grid[0])
    passages = 0
    deadends = 0
    for r in range(1, rows-1):
        for c in range(1, cols-1):
            if not grid[r][c]:
                passages += 1
                if passage_degree(grid, r, c) == 1:
                    deadends += 1
    return passages, deadends

def carve_loops_with_deadend_guard(grid, H, W, rng, ratio,
                                   min_deadend_ratio, min_deadend_abs):
    if ratio <= 0:
        return
    candidates = []
    for r in range(1, H-1):
        for c in range(1, W-1):
            if grid[r][c]:
                if r % 2 == 1 and c % 2 == 0 and (not grid[r][c-1]) and (not grid[r][c+1]):
                    candidates.append((r,c))
                if r % 2 == 0 and c % 2 == 1 and (not grid[r-1][c]) and (not grid[r+1][c]):
                    candidates.append((r,c))
    rng.shuffle(candidates)
    max_to_carve = int(len(candidates) * ratio)
    total_passages, _ = count_passages_and_deadends(grid)
    min_deadends_target = max(min_deadend_abs, math.ceil(total_passages * min_deadend_ratio))
    carved = 0
    for (r,c) in candidates:
        if carved >= max_to_carve:
            break
        grid[r][c] = False
        _, deadends_after = count_passages_and_deadends(grid)
        if deadends_after >= min_deadends_target:
            carved += 1
        else:
            grid[r][c] = True

# ---- Helpers for explorative simple path (no repeats) ----
def manhattan(a, b):
    return abs(a[0]-b[0]) + abs(a[1]-b[1])

def _neighbors_passages(grid, r, c):
    rows, cols = len(grid), len(grid[0])
    for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr, cc = r+dr, c+dc
        if 0 <= rr < rows and 0 <= cc < cols and not grid[rr][cc]:
            yield (rr, cc)

def _reachable_with_remaining(grid, start, goal, blocked):
    """BFS that forbids nodes in 'blocked'. Returns True if goal is reachable."""
    if start in blocked or goal in blocked:
        return False
    Q = deque([start])
    seen = {start}
    while Q:
        v = Q.popleft()
        if v == goal:
            return True
        r, c = v
        for nb in _neighbors_passages(grid, r, c):
            if nb not in seen and nb not in blocked:
                seen.add(nb)
                Q.append(nb)
    return False

def bfs_shortest_path(grid, start, goal):
    rows, cols = len(grid), len(grid[0])
    q = deque([start]); came = {start: None}
    def nbs(r,c):
        for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
            rr,cc = r+dr, c+dc
            if 0<=rr<rows and 0<=cc<cols and not grid[rr][cc]:
                yield rr,cc
    while q:
        cur = q.popleft()
        if cur == goal: break
        for nb in nbs(*cur):
            if nb not in came:
                came[nb] = cur; q.append(nb)
    if goal not in came: return []
    path = []; cur = goal
    while cur is not None: path.append(cur); cur = came[cur]
    return path[::-1]

def explorative_long_simple_path(grid, start, goal, rng, total_passages,
                                 cap_ratio=0.50, trials=400,
                                 turn_bias=1.3, far_bias=0.9, near_bias=0.2):
    """
    Find a long *simple* (no-repeat) path start->goal.
    Heuristics: favor turns, favor farther-from-goal early (with small near-goal pull),
    and forbid moves that cut off reachability to the goal.
    Tries many randomized runs and picks the best (preferring longest <= cap).
    """
    cap_limit = max(1, int(total_passages * cap_ratio))
    best_any = None
    best_under_cap = None

    for _ in range(trials):
        path = [start]
        visited = {start}
        prev_dir = None

        while path[-1] != goal:
            r, c = path[-1]
            cand = []
            for rr, cc in _neighbors_passages(grid, r, c):
                if (rr, cc) in visited:
                    continue
                # Reachability guard
                blocked = visited.copy()
                blocked.add((rr, cc))
                if not _reachable_with_remaining(grid, (rr, cc), goal, blocked - {(rr, cc)}):
                    continue

                # Score neighbor
                d_goal = manhattan((rr, cc), goal)
                turn_score = 0.0
                if prev_dir is not None:
                    dr, dc = rr - r, cc - c
                    turn_score = turn_bias if (dr, dc) != prev_dir else 0.0
                jitter = rng.random() * 0.1
                score = (-turn_score) + (-far_bias * d_goal) + (near_bias * (1.0 / (d_goal + 1))) + jitter
                cand.append(((rr, cc), score))

            if not cand:
                path = None
                break

            cand.sort(key=lambda x: x[1])
            topk = max(1, min(3, len(cand)))
            choice = rng.choice(cand[:topk])[0]
            dr, dc = choice[0] - r, choice[1] - c
            prev_dir = (dr, dc)
            path.append(choice)
            visited.add(choice)

        if path is None or path[-1] != goal:
            continue

        if best_any is None or len(path) > len(best_any):
            best_any = path
        if len(path) <= cap_limit and (best_under_cap is None or len(path) > len(best_under_cap)):
            best_under_cap = path

    if best_under_cap is not None:
        return best_under_cap
    if best_any is not None:
        return best_any
    return bfs_shortest_path(grid, start, goal)

def merge_rectangles(grid, rows, cols):
    g = [row[:] for row in grid]
    blocks = []
    for r in range(rows):
        c = 0
        while c < cols:
            if not g[r][c]:
                c += 1; continue
            w = 1
            while c+w < cols and g[r][c+w]:
                w += 1
            h = 1
            while r+h < rows and all(g[r+h][cc] for cc in range(c, c+w)):
                h += 1
            for rr in range(r, r+h):
                for cc in range(c, c+w):
                    g[rr][cc] = False
            blocks.append((r, c, h, w))
            c += w
    return blocks

def inward(rc, rows, cols):
    r,c = rc
    if r == 0:        return (1, c)
    if r == rows-1:   return (rows-2, c)
    if c == 0:        return (r, 1)
    if c == cols-1:   return (r, cols-2)
    return rc

# =========================
# Add-on Preferences: Color Presets
# =========================
class MMM_ColorPreset(PropertyGroup):
    name: StringProperty(name="Preset Name", default="Preset")
    col_default: FloatVectorProperty(size=4, subtype='COLOR', default=(1,1,1,1), min=0, max=1)
    col_purist:  FloatVectorProperty(size=4, subtype='COLOR', default=(0.55,0.30,0.95,1.0), min=0, max=1)
    col_explore: FloatVectorProperty(size=4, subtype='COLOR', default=(1.0,0.55,0.20,1.0), min=0, max=1)
    col_inter:   FloatVectorProperty(size=4, subtype='COLOR', default=(0.60,0.28,0.18,1.0), min=0, max=1)

class MMM_Preferences(AddonPreferences):
    bl_idname = __name__
    presets: CollectionProperty(type=MMM_ColorPreset)
    active_preset: IntProperty(name="Active Preset", default=-1)
    def draw(self, context):
        col = self.layout.column()
        col.label(text="Saved Color Presets")
        for i, pr in enumerate(self.presets):
            row = col.row(align=True)
            row.prop(pr, "name", text="")
            op = row.operator("mmm.delete_preset", text="", icon='TRASH')
            op.index = i

class MMM_OT_SavePreset(Operator):
    bl_idname = "mmm.save_preset"
    bl_label = "Save Color Preset"
    name: StringProperty(name="Preset Name", default="My Colors")
    def invoke(self, context, event): return context.window_manager.invoke_props_dialog(self)
    def execute(self, context):
        prefs = bpy.context.preferences.addons[__name__].preferences
        p = context.scene.mmm_props
        new = prefs.presets.add()
        new.name = self.name
        new.col_default = p.col_default
        new.col_purist  = p.col_purist
        new.col_explore = p.col_explore
        new.col_inter   = p.col_intersect
        prefs.active_preset = len(prefs.presets)-1
        self.report({'INFO'}, f"Saved preset '{self.name}'.")
        return {'FINISHED'}

class MMM_OT_ApplyPreset(Operator):
    bl_idname = "mmm.apply_preset"
    bl_label = "Apply Preset"
    preset_index: IntProperty(default=-1)
    def execute(self, context):
        prefs = bpy.context.preferences.addons[__name__].preferences
        idx = self.preset_index if self.preset_index >= 0 else prefs.active_preset
        if idx < 0 or idx >= len(prefs.presets):
            self.report({'WARNING'}, "No preset selected."); return {'CANCELLED'}
        pr = prefs.presets[idx]
        p = context.scene.mmm_props
        p.col_default = pr.col_default
        p.col_purist  = pr.col_purist
        p.col_explore = pr.col_explore
        p.col_intersect = pr.col_inter
        self.report({'INFO'}, f"Applied preset '{pr.name}'.")
        return {'FINISHED'}

class MMM_OT_DeletePreset(Operator):
    bl_idname = "mmm.delete_preset"
    bl_label = "Delete Preset"
    index: IntProperty()
    def execute(self, context):
        prefs = bpy.context.preferences.addons[__name__].preferences
        if 0 <= self.index < len(prefs.presets):
            prefs.presets.remove(self.index)
            prefs.active_preset = min(prefs.active_preset, len(prefs.presets)-1)
            self.report({'INFO'}, "Preset deleted."); return {'FINISHED'}
        self.report({'WARNING'}, "Invalid preset index."); return {'CANCELLED'}

def mmm_preset_items(self, context):
    prefs = bpy.context.preferences.addons[__name__].preferences
    items = []
    for i, pr in enumerate(prefs.presets):
        items.append((str(i), pr.name, "", 'PRESET', i))
    if not items:
        items.append(("NONE", "No Presets", "", 'ERROR', 0))
    return items

# =========================
# Scene Properties (with tooltips)
# =========================
class MMM_Props(PropertyGroup):
    # Size & randomness
    rows: IntProperty(name="Rows", default=20, min=5, soft_max=300,
        description="Logical passage rows (not world units). Higher = taller maze.")
    cols: IntProperty(name="Cols", default=30, min=5, soft_max=300,
        description="Logical passage columns. Higher = wider maze.")
    seed: IntProperty(name="Seed", default=12345, soft_min=0,
        description="Random seed for reproducible mazes. Toggle 'Use Random Seed' to ignore.")
    randomize: BoolProperty(name="Use Random Seed", default=False,
        description="If ON, uses a fresh random seed each time (non-reproducible).")

    # Geometry
    cell_w: FloatProperty(name="Cell W", default=2.5, min=0.01,
        description="World width (X) of a single grid cell (Blender units).")
    cell_h: FloatProperty(name="Cell H", default=2.5, min=0.01,
        description="World depth (Y) of a single grid cell (Blender units).")
    height_min: FloatProperty(name="Wall H min", default=7.0, min=0.01,
        description="Minimum wall height when 'Uniform Height' is OFF.")
    height_max: FloatProperty(name="Wall H max", default=20.0, min=0.01,
        description="Maximum wall height when 'Uniform Height' is OFF. If 'Uniform Height' is ON, this is the constant height.")
    uniform_height: BoolProperty(name="Uniform Height", default=False,
        description="If ON, all walls use 'Wall H max'. If OFF, heights vary between min and max.")

    # Loops & dead-ends
    extra_loop_ratio: FloatProperty(name="Loop Ratio", default=0.06, min=0.0, max=1.0,
        description="0..1: Fraction of eligible walls converted to loops (adds multiple solutions). Recommend 0.03–0.12.")
    keep_deadend_min_ratio: FloatProperty(name="Min Dead-End Ratio", default=0.06, min=0.0, max=1.0,
        description="Minimum fraction of passage cells that must remain dead-ends.")
    keep_deadend_min_count: IntProperty(name="Min Dead-End Count", default=6, min=0,
        description="Absolute minimum number of cul-de-sacs to preserve.")

    # Exploration cap
    max_explore_coverage: FloatProperty(name="Max Explore Coverage", default=0.50, min=0.0, max=1.0,
        description="Caps unique cells highlighted as 'Explorative'. 0.50 = at most 50% of all passages.")

    # Explorative route tuning
    exp_trials: IntProperty(
        name="Explorative Trials", default=400, min=50, soft_max=5000,
        description="How many randomized self-avoiding walks to try. Higher finds longer paths but is slower."
    )
    exp_turn_bias: FloatProperty(
        name="Turn Bias", default=1.30, min=0.0, soft_max=4.0,
        description="Preference for turning vs going straight. Higher = more turns/zigzags."
    )
    exp_far_bias: FloatProperty(
        name="Far Bias", default=0.90, min=0.0, soft_max=3.0,
        description="Preference for staying farther from the goal early on. Higher = more meander before homing in."
    )
    exp_near_bias: FloatProperty(
        name="Near Bias", default=0.20, min=0.0, soft_max=2.0,
        description="Small pull toward the goal so paths still finish. Raise slightly if paths fail to reach the exit."
    )

    # Floor
    make_floor: BoolProperty(name="Make Floor", default=True,
        description="Add a thin floor under the maze for context.")
    floor_thickness: FloatProperty(name="Floor Thickness", default=0.2, min=0.0,
        description="Thickness of the floor slab.")

    # Colors (RGBA)
    col_default: FloatVectorProperty(name="Blocked/Default", subtype='COLOR', size=4,
        default=(1.0, 1.0, 1.0, 1.0), min=0.0, max=1.0,
        description="Color for all other walls (not on Purist/Explorative/Intersection).")
    col_purist: FloatVectorProperty(name="Purist (Efficient)", subtype='COLOR', size=4,
        default=(0.55, 0.30, 0.95, 1.0), min=0.0, max=1.0,
        description="Color for walls bordering the shortest start→end path.")
    col_explore: FloatVectorProperty(name="Explorative", subtype='COLOR', size=4,
        default=(1.0, 0.55, 0.20, 1.0), min=0.0, max=1.0,
        description="Color for walls bordering the longer simple route.")
    col_intersect: FloatVectorProperty(name="Intersecting", subtype='COLOR', size=4,
        default=(0.60, 0.28, 0.18, 1.0), min=0.0, max=1.0,
        description="Color for walls that border BOTH routes (overlap).")

    # Material names
    mat_default_name: StringProperty(name="Mat Default", default="MazeWall", description="Material name for default/blocked walls.")
    mat_purist_name:  StringProperty(name="Mat Purist",  default="MazePathEfficient", description="Material name for Purist walls.")
    mat_explore_name: StringProperty(name="Mat Explorative", default="MazePathExplore", description="Material name for Explorative walls.")
    mat_inter_name:   StringProperty(name="Mat Intersect", default="MazePathIntersect", description="Material name for Intersection walls.")
    mat_floor_name:   StringProperty(name="Mat Floor", default="MazeFloor", description="Material name for the floor.")

    # Cleanup
    clear_meshes_first: BoolProperty(name="Clear Existing Meshes", default=True,
        description="If ON, empties the 'maze' collection before generating a new maze.")

    # Preset selector
    preset_enum: EnumProperty(name="Presets", items=mmm_preset_items, description="Select a saved color preset to apply.")

    # ---------------- Navigator & Trail ----------------
    nav_path_type: EnumProperty(
        name="Navigator Path",
        items=[('PURIST', "Purist (Shortest)", "Animate along the BFS shortest path"),
               ('EXPLORE', "Explorative (Long, Simple)", "Animate along the longer simple path (no repeats)")],
        default='PURIST',
        description="Choose which route the navigator will follow."
    )
    nav_color: FloatVectorProperty(
        name="Navigator Color", subtype='COLOR', size=4,
        default=(0.1, 0.9, 0.1, 1.0), min=0.0, max=1.0,
        description="Color for the moving navigator cube."
    )
    trail_color: FloatVectorProperty(
        name="Trail Color", subtype='COLOR', size=4,
        default=(0.1, 0.8, 0.8, 1.0), min=0.0, max=1.0,
        description="Color for the trail tiles left behind."
    )
    nav_size: FloatProperty(
        name="Navigator Size", default=0.6, min=0.05,
        description="Edge length of the navigator cube (Blender units)."
    )
    trail_tile_size: FloatProperty(
        name="Trail Tile Size", default=0.7, min=0.05,
        description="Footprint width/length of each trail tile (Blender units)."
    )
    trail_tile_height: FloatProperty(
        name="Trail Tile Height", default=0.2, min=0.01,
        description="Height of each trail tile (Blender units)."
    )
    nav_start_frame: IntProperty(
        name="Start Frame", default=1, min=1,
        description="Animation start frame for the navigator."
    )
    nav_step_frames: IntProperty(
        name="Frames per Step", default=6, min=1,
        description="How many frames between path cells for the navigator."
    )
    trail_grow_frames: IntProperty(
        name="Trail Grow Frames", default=4, min=1,
        description="How many frames each trail tile takes to scale from 0→1 (growth)."
    )
    nav_clear_old: BoolProperty(
        name="Clear Old Navigator", default=True,
        description="If ON, removes previous Navigator_* and Trail_* objects before creating a new one."
    )

# =========================
# Generate (builds maze, colors, and caches both routes)
# =========================
class MMM_OT_Generate(Operator):
    bl_idname = "mmm.generate"
    bl_label = "Generate Maze"
    bl_description = "Generate a Prim's maze with colored wall categories in the 'maze' collection"

    def execute(self, context):
        global LAST_MAZE_CACHE
        p = context.scene.mmm_props
        rng = random.Random(None if p.randomize else p.seed)

        maze_col = get_maze_collection("maze")
        if p.clear_meshes_first:
            clear_collection_objects(maze_col)

        bitmap, rows, cols, start_open, end_open = prims_maze(p.rows, p.cols, rng)
        carve_loops_with_deadend_guard(
            bitmap, rows, cols, rng,
            p.extra_loop_ratio,
            p.keep_deadend_min_ratio,
            p.keep_deadend_min_count
        )

        start_rc = inward(start_open, rows, cols)
        end_rc   = inward(end_open, rows, cols)

        # Paths
        efficient_path = bfs_shortest_path(bitmap, start_rc, end_rc)
        total_passages, deadends = count_passages_and_deadends(bitmap)

        # Optional clamps for safety
        trials = max(50, int(p.exp_trials))
        turn_b = max(0.0, float(p.exp_turn_bias))
        far_b  = max(0.0, float(p.exp_far_bias))
        near_b = max(0.0, float(p.exp_near_bias))

        explorative_path = explorative_long_simple_path(
            bitmap, start_rc, end_rc, rng,
            total_passages=total_passages,
            cap_ratio=p.max_explore_coverage,   # prefers <= cap when possible
            trials=trials,
            turn_bias=turn_b, far_bias=far_b, near_bias=near_b
        )

        eff_set = set(efficient_path)
        exp_capped_set = set(explorative_path)  # now the exact longer simple path

        # World layout
        total_w, total_h = cols*p.cell_w, rows*p.cell_h
        off_x, off_y = -total_w/2 + p.cell_w/2, -total_h/2 + p.cell_h/2

        # Materials
        mat_default = ensure_solid_material(p.mat_default_name, rgba=tuple(p.col_default))
        mat_purist  = ensure_solid_material(p.mat_purist_name,  rgba=tuple(p.col_purist))
        mat_explore = ensure_solid_material(p.mat_explore_name, rgba=tuple(p.col_explore))
        mat_inter   = ensure_solid_material(p.mat_inter_name,   rgba=tuple(p.col_intersect))
        mat_floor   = ensure_solid_material(p.mat_floor_name,   rgba=(0.15,0.15,0.17,1.0))

        def wall_touches_set(r, c, passage_set):
            if is_border_cell(r, c, rows, cols): return False
            for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
                rr, cc = r+dr, c+dc
                if (rr, cc) in passage_set:
                    return True
            return False

        # Build walls into 'maze'
        wall_blocks = merge_rectangles(bitmap, rows, cols)
        for (r, c, h, w) in wall_blocks:
            sx, sy = w*p.cell_w, h*p.cell_h
            sz = (p.height_max if p.uniform_height else random.uniform(p.height_min, p.height_max))
            cx = off_x + c*p.cell_w + (w-1)*p.cell_w/2
            cy = -(off_y + r*p.cell_h + (h-1)*p.cell_h/2)

            mark_eff = mark_exp = False
            for rr in range(r, r+h):
                for cc in range(c, c+w):
                    if wall_touches_set(rr, cc, eff_set): mark_eff = True
                    if wall_touches_set(rr, cc, exp_capped_set): mark_exp = True
                if mark_eff and mark_exp: break

            mat = mat_inter if (mark_eff and mark_exp) else (mat_purist if mark_eff else (mat_explore if mark_exp else mat_default))

            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, 0.0))
            ob = bpy.context.active_object
            ob.name = f"MazeWall_{r}_{c}_{h}x{w}"
            ob.dimensions = (sx, sy, sz)
            sit_on_ground(ob)
            if ob.data.materials: ob.data.materials[0] = mat
            else: ob.data.materials.append(mat)
            link_exclusive(ob, maze_col)

        # Optional floor
        if p.make_floor:
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
            floor = bpy.context.active_object
            floor.name = "MazeFloor"
            floor.dimensions = (total_w + p.cell_w, total_h + p.cell_h, p.floor_thickness)
            sit_on_ground(floor)
            if floor.data.materials: floor.data.materials[0] = mat_floor
            else: floor.data.materials.append(mat_floor)
            link_exclusive(floor, maze_col)

        coverage_pct = 100.0 * len(explorative_path) / max(1, total_passages)
        self.report({'INFO'},
            f"Maze {p.rows}x{p.cols} | Dead-ends: {deadends} | "
            f"Purist len: {len(efficient_path)} | Explorative len: {len(explorative_path)} "
            f"({coverage_pct:.1f}% of passages)")

        # Cache for Navigator
        LAST_MAZE_CACHE = {
            "bitmap": bitmap, "rows": rows, "cols": cols,
            "start_rc": start_rc, "end_rc": end_rc,
            "efficient_path": efficient_path,
            "explorative_path": explorative_path,
            "exp_capped_set": set(explorative_path),
            "off_x": off_x, "off_y": off_y,
            "cell_w": p.cell_w, "cell_h": p.cell_h,
        }
        return {'FINISHED'}

# =========================
# Merge + Export
# =========================
class MMM_OT_ExportMerged(Operator):
    bl_idname = "mmm.export_merged"
    bl_label = "Export: Merge to Single Mesh"
    bl_description = "Duplicate all maze walls (and optional floor) and merge them into a single mesh named 'MazeMerged' (originals preserved)."
    include_floor: BoolProperty(name="Include Floor", default=True, description="If ON, include the floor in the merge.")
    merged_name: StringProperty(name="Merged Name", default="MazeMerged", description="Name for the merged object.")
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    def execute(self, context):
        maze_col = get_maze_collection("maze")
        src = [o for o in maze_col.objects if o.type == 'MESH' and (o.name.startswith("MazeWall_") or o.name == "MazeFloor")]
        if not self.include_floor:
            src = [o for o in src if o.name != "MazeFloor"]
        if not src:
            self.report({'WARNING'}, "No maze meshes found to merge.")
            return {'CANCELLED'}
        select_only(src)
        bpy.ops.object.duplicate()
        dups = [o for o in bpy.context.view_layer.objects if o.select_get()]
        if not dups:
            self.report({'WARNING'}, "Duplication failed."); return {'CANCELLED'}
        bpy.context.view_layer.objects.active = dups[0]
        try: bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        except: pass
        bpy.ops.object.join()
        merged = bpy.context.view_layer.objects.active
        merged.name = self.merged_name
        merged.data = merged.data.copy()
        link_exclusive(merged, maze_col)
        self.report({'INFO'}, f"Merged {len(src)} objects into '{merged.name}'.")
        return {'FINISHED'}

class MMM_OT_ExportFiles(Operator):
    bl_idname = "mmm.export_files"
    bl_label = "Export Maze (OBJ / FBX / GLB)"
    bl_description = "Export maze collection to OBJ, FBX, or GLB. Choose Separate Objects or Single Merged Mesh."
    export_format: EnumProperty(
        name="Format",
        items=[('OBJ', "OBJ", "Wavefront OBJ"),
               ('FBX', "FBX", "Autodesk FBX"),
               ('GLB', "GLB", "glTF Binary (.glb)")],
        default='GLB',
        description="File format to export."
    )
    include_floor: BoolProperty(
        name="Include Floor", default=True,
        description="If ON, includes the floor object in the export."
    )
    join_mode: EnumProperty(
        name="Export Mode",
        items=[('SEPARATE', "Separate Objects", "Export each maze object as-is (no merge)"),
               ('MERGED', "Single Merged Mesh", "Export a temporary joined mesh (originals preserved)")],
        default='SEPARATE',
        description="Choose whether to export objects separately or as one merged mesh."
    )
    filepath: StringProperty(name="File Path", subtype='FILE_PATH')
    def invoke(self, context, event):
        ext = { 'OBJ': ".obj", 'FBX': ".fbx", 'GLB': ".glb" }[self.export_format]
        if not self.filepath:
            self.filepath = bpy.path.abspath(f"//maze_export{ext}")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    def execute(self, context):
        maze_col = get_maze_collection("maze")
        objs = [o for o in maze_col.objects if o.type == 'MESH' and (o.name.startswith("MazeWall_") or o.name == "MazeFloor")]
        if not self.include_floor:
            objs = [o for o in objs if o.name != "MazeFloor"]
        if not objs:
            self.report({'WARNING'}, "No maze meshes found to export.")
            return {'CANCELLED'}

        temp_obj = None
        export_set = objs
        if self.join_mode == 'MERGED':
            select_only(objs)
            bpy.ops.object.duplicate()
            dups = [o for o in bpy.context.view_layer.objects if o.select_get()]
            if not dups:
                self.report({'WARNING'}, "Duplication failed.")
                return {'CANCELLED'}
            bpy.context.view_layer.objects.active = dups[0]
            try: bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            except: pass
            bpy.ops.object.join()
            temp_obj = bpy.context.view_layer.objects.active
            temp_obj.name = "MazeExport_Temp"
            link_exclusive(temp_obj, maze_col)
            export_set = [temp_obj]

        select_only(export_set)

        fp = bpy.path.abspath(self.filepath)
        dirname = os.path.dirname(fp)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)

        try:
            if self.export_format == 'OBJ':
                bpy.ops.wm.obj_export(filepath=fp, export_selected_objects=True)
            elif self.export_format == 'FBX':
                bpy.ops.export_scene.fbx(filepath=fp, use_selection=True, apply_scale_options='FBX_SCALE_NONE')
            elif self.export_format == 'GLB':
                bpy.ops.export_scene.gltf(filepath=fp, export_format='GLB', use_selection=True)
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {e}")
            if temp_obj:
                select_only([temp_obj]); bpy.ops.object.delete()
            return {'CANCELLED'}

        if temp_obj:
            select_only([temp_obj]); bpy.ops.object.delete()

        self.report({'INFO'}, f"Exported maze to {fp}")
        return {'FINISHED'}

# =========================
# Navigator + Trail (uses cached paths)
# =========================
class MMM_OT_CreateNavigator(Operator):
    bl_idname = "mmm.create_navigator"
    bl_label = "Create Navigator + Trail"
    bl_description = "Create a small cube that keyframes along the chosen route and leaves a growing trail of tiles."

    def execute(self, context):
        global LAST_MAZE_CACHE
        p = context.scene.mmm_props
        if LAST_MAZE_CACHE is None:
            self.report({'WARNING'}, "Generate a maze first (so the navigator matches it).")
            return {'CANCELLED'}

        cache = LAST_MAZE_CACHE
        off_x = cache["off_x"]; off_y = cache["off_y"]
        cell_w = cache["cell_w"]; cell_h = cache["cell_h"]

        # Choose the path sequence
        if p.nav_path_type == 'PURIST':
            route = list(cache["efficient_path"])
            nav_name = "Navigator_Purist"
            trail_prefix = "Trail_Purist_"
        else:
            route = list(cache["explorative_path"])  # already simple, no repeats
            nav_name = "Navigator_Explore"
            trail_prefix = "Trail_Explore_"

        if len(route) < 2:
            self.report({'WARNING'}, "Path is too short to animate.")
            return {'CANCELLED'}

        # Optional cleanup
        maze_col = get_maze_collection("maze")
        if p.nav_clear_old:
            old = [o for o in maze_col.objects if o.name.startswith("Navigator_") or o.name.startswith("Trail_")]
            if old:
                select_only(old); bpy.ops.object.delete()

        # Materials
        mat_nav  = ensure_solid_material("MazeNavigator", rgba=tuple(p.nav_color))
        mat_trail = ensure_solid_material("MazeTrail",   rgba=tuple(p.trail_color))

        def rc_to_world(rc):
            r,c = rc
            x = off_x + c*cell_w
            y = -(off_y + r*cell_h)
            return x,y

        # Navigator cube
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
        agent = bpy.context.active_object
        agent.name = nav_name
        agent.dimensions = (p.nav_size, p.nav_size, p.nav_size)
        sit_on_ground(agent)
        if agent.data.materials: agent.data.materials[0] = mat_nav
        else: agent.data.materials.append(mat_nav)
        link_exclusive(agent, maze_col)

        # Animate navigator per-step (keyframes)
        f0 = p.nav_start_frame
        step = max(1, int(p.nav_step_frames))
        for i, rc in enumerate(route):
            x,y = rc_to_world(rc)
            agent.location.x = x
            agent.location.y = y
            agent.keyframe_insert(data_path="location", frame=f0 + i*step)

        # Trail tiles that grow
        grow = max(1, int(p.trail_grow_frames))
        tile_w = p.trail_tile_size
        tile_h = p.trail_tile_size
        tile_z = p.trail_tile_height

        for i, rc in enumerate(route):
            x,y = rc_to_world(rc)
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, 0.0))
            tile = bpy.context.active_object
            tile.name = f"{trail_prefix}{i:04d}"
            tile.dimensions = (tile_w, tile_h, tile_z)
            sit_on_ground(tile)
            if tile.data.materials: tile.data.materials[0] = mat_trail
            else: tile.data.materials.append(mat_trail)
            link_exclusive(tile, maze_col)

            # Animate growth: scale from 0 -> 1 over 'grow' frames
            tile.scale = (0.001, 0.001, 1.0)
            tile.keyframe_insert(data_path="scale", frame=f0 + i*step)
            tile.scale = (1.0, 1.0, 1.0)
            tile.keyframe_insert(data_path="scale", frame=f0 + i*step + grow)

        self.report({'INFO'}, f"Navigator created on {p.nav_path_type} path with {len(route)} steps.")
        return {'FINISHED'}

# =========================
# UI Panel
# =========================
class MMM_PT_Panel(Panel):
    bl_label = "Mo's Maze Maker"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mo's Maze Maker"

    def draw(self, context):
        p = context.scene.mmm_props
        layout = self.layout

        box = layout.box()
        box.label(text="Maze Size & Seed")
        row = box.row(align=True); row.prop(p, "rows"); row.prop(p, "cols")
        row = box.row(align=True); row.prop(p, "randomize")
        if not p.randomize: row.prop(p, "seed")
        box.label(text="Tip: Rows/Cols control logical cells, not world units.", icon='INFO')

        box = layout.box()
        box.label(text="Geometry")
        row = box.row(align=True); row.prop(p, "cell_w"); row.prop(p, "cell_h")
        row = box.row(align=True); row.prop(p, "height_min"); row.prop(p, "height_max")
        box.prop(p, "uniform_height")
        box.label(text="Tip: Cell W/H are per-cell size; heights vary unless 'Uniform' is on.", icon='INFO')

        box = layout.box()
        box.label(text="Loops & Dead-Ends")
        box.prop(p, "extra_loop_ratio")
        row = box.row(align=True); row.prop(p, "keep_deadend_min_ratio"); row.prop(p, "keep_deadend_min_count")
        box.label(text="Tip: Loop Ratio ~0.03–0.12 adds cycles; dead-end guards keep cul-de-sacs.", icon='INFO')

        box = layout.box()
        box.label(text="Exploration")
        box.prop(p, "max_explore_coverage")
        # --- Explorative Tuning ---
        row = box.row(align=True); row.prop(p, "exp_trials")
        row = box.row(align=True); row.prop(p, "exp_turn_bias"); row.prop(p, "exp_far_bias")
        row = box.row(align=True); row.prop(p, "exp_near_bias")
        box.label(text="Tip: Higher Trials finds longer routes; Turn/Far bias increase meander; Near bias helps ensure finish.", icon='INFO')

        box = layout.box()
        box.label(text="Floor")
        box.prop(p, "make_floor")
        box.prop(p, "floor_thickness")

        box = layout.box()
        box.label(text="Colors (RGBA)")
        box.prop(p, "col_purist")
        box.prop(p, "col_explore")
        box.prop(p, "col_intersect")
        box.prop(p, "col_default")

        box = layout.box()
        box.label(text="Material Names (optional)")
        box.prop(p, "mat_purist_name"); box.prop(p, "mat_explore_name")
        box.prop(p, "mat_inter_name");  box.prop(p, "mat_default_name")
        box.prop(p, "mat_floor_name")

        layout.separator()
        layout.prop(p, "clear_meshes_first")
        layout.operator("mmm.generate", icon='MESH_CUBE', text="Generate Maze")

        layout.separator()
        # Presets
        prefs = bpy.context.preferences.addons[__name__].preferences
        box = layout.box()
        box.label(text="Color Presets")
        if prefs.presets:
            box.prop(p, "preset_enum", text="Select")
            row = box.row(align=True)
            idx = int(p.preset_enum) if p.preset_enum and p.preset_enum != "NONE" else prefs.active_preset
            apply = row.operator("mmm.apply_preset", text="Apply", icon='CHECKMARK')
            apply.preset_index = idx if idx is not None else -1
        row = box.row(align=True)
        row.operator("mmm.save_preset", text="Save Current as Preset", icon='ADD')

        layout.separator()
        # Merge + Export
        row = layout.row(align=True)
        row.operator("mmm.export_merged", icon='AUTOMERGE_ON')
        box = layout.box()
        box.label(text="Export (OBJ / FBX / GLB)")
        box.operator("mmm.export_files", text="Export…", icon='EXPORT')
        box.label(text="Pick format and Separate vs Merged in the dialog.", icon='INFO')

        layout.separator()
        # Navigator UI
        nav = layout.box()
        nav.label(text="Navigator")
        nav.prop(p, "nav_path_type")
        row = nav.row(align=True); row.prop(p, "nav_color"); row.prop(p, "trail_color")
        row = nav.row(align=True); row.prop(p, "nav_size"); row.prop(p, "trail_tile_size")
        row = nav.row(align=True); row.prop(p, "trail_tile_height")
        row = nav.row(align=True); row.prop(p, "nav_start_frame"); row.prop(p, "nav_step_frames")
        nav.prop(p, "trail_grow_frames")
        nav.prop(p, "nav_clear_old")
        nav.operator("mmm.create_navigator", icon='ANIM')

# =========================
# Register
# =========================
classes = (
    MMM_ColorPreset, MMM_Preferences,
    MMM_Props,
    MMM_OT_Generate,
    MMM_OT_ExportMerged,
    MMM_OT_SavePreset, MMM_OT_ApplyPreset, MMM_OT_DeletePreset,
    MMM_OT_ExportFiles,
    MMM_OT_CreateNavigator,
    MMM_PT_Panel,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.mmm_props = PointerProperty(type=MMM_Props)

def unregister():
    del bpy.types.Scene.mmm_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
