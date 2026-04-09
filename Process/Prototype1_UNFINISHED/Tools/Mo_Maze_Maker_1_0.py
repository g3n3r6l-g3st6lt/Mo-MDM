bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G. (plus some ChatGPT)",
    "version": (1, 2, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A Prim's maze-generator that explores efficiency vs. exploration.",
    "category": "Add Mesh",
}

import bpy, random, math, os
from mathutils import Vector
from collections import deque
from bpy.props import (
    IntProperty, FloatProperty, BoolProperty, FloatVectorProperty,
    PointerProperty, StringProperty, EnumProperty, CollectionProperty
)
from bpy.types import Operator, Panel, PropertyGroup, AddonPreferences

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
        try:
            o.select_set(True)
        except:
            pass
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

def dfs_cover_path(grid, start, goal, rng):
    rows, cols = len(grid), len(grid[0])
    def neighbors(rc):
        r,c = rc
        outs=[]
        for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
            rr,cc=r+dr,c+dc
            if 0<=rr<rows and 0<=cc<cols and not grid[rr][cc]:
                outs.append((rr,cc))
        outs.sort(key=lambda p: (passage_degree(grid,p[0],p[1]), -abs(p[0]-goal[0]) - abs(p[1]-goal[1])))
        return outs
    visited = set([start])
    stack = [start]
    trail = [start]
    while stack:
        v = stack[-1]
        unvis = [u for u in neighbors(v) if u not in visited]
        if unvis:
            u = unvis[0]
            visited.add(u)
            stack.append(u)
            trail.append(u)
        else:
            stack.pop()
            if stack:
                trail.append(stack[-1])
    if trail[-1] != goal:
        tail = bfs_shortest_path(grid, trail[-1], goal)
        if tail:
            trail.extend(tail[1:])
    return trail

def limit_exploration_coverage(trail, limit_ratio, total_passages):
    cap = max(1, int(math.floor(total_passages * limit_ratio)))
    chosen = set()
    for rc in trail:
        if rc not in chosen:
            chosen.add(rc)
            if len(chosen) >= cap:
                break
    return chosen

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
# Scene Properties (with descriptive tooltips)
# =========================
class MMM_Props(PropertyGroup):
    # Size & randomness
    rows: IntProperty(
        name="Rows", default=20, min=5, soft_max=300,
        description="Logical passage rows (not world units). Higher = taller maze."
    )
    cols: IntProperty(
        name="Cols", default=30, min=5, soft_max=300,
        description="Logical passage columns. Higher = wider maze."
    )
    seed: IntProperty(
        name="Seed", default=12345, soft_min=0,
        description="Random seed for reproducible mazes. Toggle 'Use Random Seed' to ignore this."
    )
    randomize: BoolProperty(
        name="Use Random Seed", default=False,
        description="If ON, uses a fresh random seed each time (non-reproducible)."
    )

    # Geometry
    cell_w: FloatProperty(
        name="Cell W", default=2.5, min=0.01,
        description="World width (X) of a single grid cell (in Blender units)."
    )
    cell_h: FloatProperty(
        name="Cell H", default=2.5, min=0.01,
        description="World depth (Y) of a single grid cell (in Blender units)."
    )
    height_min: FloatProperty(
        name="Wall H min", default=7.0, min=0.01,
        description="Minimum wall height when 'Uniform Height' is OFF."
    )
    height_max: FloatProperty(
        name="Wall H max", default=20.0, min=0.01,
        description="Maximum wall height when 'Uniform Height' is OFF. If 'Uniform Height' is ON, this is the constant height."
    )
    uniform_height: BoolProperty(
        name="Uniform Height", default=False,
        description="If ON, all walls use 'Wall H max'. If OFF, heights vary between min and max."
    )

    # Loops & dead-ends
    extra_loop_ratio: FloatProperty(
        name="Loop Ratio", default=0.06, min=0.0, max=1.0,
        description="0..1: Fraction of eligible walls converted to loops (adds multiple solutions). Small values (0.03–0.12) recommended."
    )
    keep_deadend_min_ratio: FloatProperty(
        name="Min Dead-End Ratio", default=0.06, min=0.0, max=1.0,
        description="Minimum fraction of passage cells that must remain dead-ends (keeps maze feel)."
    )
    keep_deadend_min_count: IntProperty(
        name="Min Dead-End Count", default=6, min=0,
        description="Absolute minimum number of cul-de-sacs to preserve."
    )

    # Exploration cap
    max_explore_coverage: FloatProperty(
        name="Max Explore Coverage", default=0.50, min=0.0, max=1.0,
        description="Caps unique cells highlighted as 'Explorative'. 0.50 = at most 50% of all passages."
    )

    # Floor
    make_floor: BoolProperty(
        name="Make Floor", default=True,
        description="Add a thin floor under the maze for context."
    )
    floor_thickness: FloatProperty(
        name="Floor Thickness", default=0.2, min=0.0,
        description="Thickness of the floor slab."
    )

    # Colors (RGBA)
    col_default: FloatVectorProperty(
        name="Blocked/Default", subtype='COLOR', size=4,
        default=(1.0, 1.0, 1.0, 1.0), min=0.0, max=1.0,
        description="Color for all other walls (not on Purist/Explorative/Intersection)."
    )
    col_purist: FloatVectorProperty(
        name="Purist (Efficient)", subtype='COLOR', size=4,
        default=(0.55, 0.30, 0.95, 1.0), min=0.0, max=1.0,
        description="Color for walls bordering the shortest start→end path."
    )
    col_explore: FloatVectorProperty(
        name="Explorative", subtype='COLOR', size=4,
        default=(1.0, 0.55, 0.20, 1.0), min=0.0, max=1.0,
        description="Color for walls bordering the capped high-coverage route."
    )
    col_intersect: FloatVectorProperty(
        name="Intersecting", subtype='COLOR', size=4,
        default=(0.60, 0.28, 0.18, 1.0), min=0.0, max=1.0,
        description="Color for walls that border BOTH routes (overlap)."
    )

    # Material names
    mat_default_name: StringProperty(name="Mat Default", default="MazeWall", description="Material name for default/blocked walls.")
    mat_purist_name:  StringProperty(name="Mat Purist", default="MazePathEfficient", description="Material name for Purist walls.")
    mat_explore_name: StringProperty(name="Mat Explorative", default="MazePathExplore", description="Material name for Explorative walls.")
    mat_inter_name:   StringProperty(name="Mat Intersect", default="MazePathIntersect", description="Material name for Intersection walls.")
    mat_floor_name:   StringProperty(name="Mat Floor", default="MazeFloor", description="Material name for the floor.")

    # Cleanup
    clear_meshes_first: BoolProperty(
        name="Clear Existing Meshes", default=True,
        description="If ON, empties the 'maze' collection before generating a new maze."
    )

    # Preset selector
    preset_enum: EnumProperty(name="Presets", items=mmm_preset_items, description="Select a saved color preset to apply.")

# =========================
# Operators: Generate
# =========================
class MMM_OT_Generate(Operator):
    bl_idname = "mmm.generate"
    bl_label = "Generate Maze"
    bl_description = "Generate a Prim's maze with colored wall categories in the 'maze' collection"

    def execute(self, context):
        p = context.scene.mmm_props
        rng = random.Random(None if p.randomize else p.seed)

        maze_col = get_maze_collection("maze")
        if p.clear_meshes_first:
            clear_collection_objects(maze_col)

        # 1) Maze
        bitmap, rows, cols, start_open, end_open = prims_maze(p.rows, p.cols, rng)

        # 2) Loops with dead-end guard
        carve_loops_with_deadend_guard(
            bitmap, rows, cols, rng,
            p.extra_loop_ratio,
            p.keep_deadend_min_ratio,
            p.keep_deadend_min_count
        )

        # 3) Paths & cap
        start_rc = inward(start_open, rows, cols)
        end_rc   = inward(end_open, rows, cols)
        efficient_path = bfs_shortest_path(bitmap, start_rc, end_rc)
        explore_trail  = dfs_cover_path(bitmap, start_rc, end_rc, rng)

        total_passages, deadends = count_passages_and_deadends(bitmap)
        eff_set = set(efficient_path)
        exp_capped_set = limit_exploration_coverage(explore_trail, p.max_explore_coverage, total_passages)

        # 4) World layout
        total_w, total_h = cols*p.cell_w, rows*p.cell_h
        off_x, off_y = -total_w/2 + p.cell_w/2, -total_h/2 + p.cell_h/2

        # 5) Materials
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

        # 6) Build walls into 'maze'
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

            if mark_eff and mark_exp: mat = mat_inter
            elif mark_eff: mat = mat_purist
            elif mark_exp: mat = mat_explore
            else: mat = mat_default

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

        coverage_pct = 100.0 * len(exp_capped_set) / max(1, total_passages)
        self.report({'INFO'},
            f"Maze {p.rows}x{p.cols} | Dead-ends: {deadends} | "
            f"Eff path: {len(efficient_path)} | Explore cov: {coverage_pct:.1f}%")
        return {'FINISHED'}

# =========================
# Operators: Merge + Export (with explicit export mode)
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
# UI Panel (with brief descriptors)
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
        box.label(text="Tip: Cell W/H are world size per cell; heights vary unless 'Uniform' is on.", icon='INFO')

        box = layout.box()
        box.label(text="Loops & Dead-Ends")
        box.prop(p, "extra_loop_ratio")
        row = box.row(align=True); row.prop(p, "keep_deadend_min_ratio"); row.prop(p, "keep_deadend_min_count")
        box.label(text="Tip: Loop Ratio ~0.03–0.12 adds cycles; dead-end guards keep cul-de-sacs.", icon='INFO')

        box = layout.box()
        box.label(text="Exploration")
        box.prop(p, "max_explore_coverage")
        box.label(text="Tip: 0.50 means at most half of all passages are used for the explorative route.", icon='INFO')

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
        box.label(text="Material Names (optional overrides)")
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
        op = box.operator("mmm.export_files", text="Export…", icon='EXPORT')
        box.label(text="Choose format and 'Export Mode' in the dialog (Separate vs Single Mesh).", icon='INFO')

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
