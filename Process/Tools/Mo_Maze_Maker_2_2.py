bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G's brain + ChatGPT's brawn)",
    "version": (2, 2, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A maze generator to explore parsimony.",
    "category": "Add Mesh",
}

import bpy, random, math, os, copy
from mathutils import Vector
from collections import deque, Counter
from heapq import heappush, heappop
from bpy.props import (IntProperty, FloatProperty, BoolProperty, FloatVectorProperty,
                       PointerProperty, StringProperty, EnumProperty)
from bpy.types import Operator, Panel, PropertyGroup

# -------- small utils --------
def get_collection(name):
    col = bpy.data.collections.get(name)
    if not col:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col

def clear_collection(col, name_prefixes=None):
    for ob in list(col.objects):
        if (name_prefixes is None) or any(ob.name.startswith(p) for p in name_prefixes):
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            bpy.data.objects.remove(ob)

def link_exclusive(ob, target_col):
    if target_col not in ob.users_collection:
        target_col.objects.link(ob)
    for c in list(ob.users_collection):
        if c != target_col:
            c.objects.unlink(ob)

def ensure_mat(name, rgba=(1,1,1,1)):
    m = bpy.data.materials.get(name)
    if not m:
        m = bpy.data.materials.new(name=name); m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = rgba
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m

def sit_on_ground(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    o_eval = obj.evaluated_get(dg)
    bb = [o_eval.matrix_world @ Vector(c) for c in o_eval.bound_box]
    min_z = min(v.z for v in bb); obj.location.z -= min_z

def rc_to_world(off_x, off_y, cell_w, cell_h, rc):
    r,c=rc; return off_x + c*cell_w, -(off_y + r*cell_h)

# -------- maze (Prim's) + helpers --------
# bitmap: True=wall, False=passage
def prims_maze(rows, cols, rng):
    H, W = rows*2+1, cols*2+1
    g = [[True]*W for _ in range(H)]
    sr, sc = rng.randrange(rows), rng.randrange(cols)
    r, c = sr*2+1, sc*2+1
    g[r][c] = False
    front=[]
    def push(r,c):
        for dr,dc in ((-2,0),(2,0),(0,-2),(0,2)):
            rr,cc=r+dr,c+dc
            if 1<=rr<H-1 and 1<=cc<W-1 and g[rr][cc]:
                front.append(((rr,cc),(r+dr//2,c+dc//2)))
    push(r,c)
    while front:
        i=rng.randrange(len(front))
        (rr,cc),(wr,wc)=front.pop(i)
        if g[rr][cc]:
            g[wr][wc]=False; g[rr][cc]=False; push(rr,cc)
    start=end=None
    for r in range(1,H-1):
        if not g[r][1]: g[r][0]=False; start=(r,0); break
    for r in range(H-2,0,-1):
        if not g[r][W-2]: g[r][W-1]=False; end=(r,W-1); break
    return g, H, W, start, end

def inward(rc, rows, cols):
    r,c=rc
    if r==0: return (1,c)
    if r==rows-1: return (rows-2,c)
    if c==0: return (r,1)
    if c==cols-1: return (r,cols-2)
    return rc

def merge_rectangles(grid, rows, cols):
    g=[row[:] for row in grid]
    blocks=[]
    for r in range(rows):
        c=0
        while c<cols:
            if not g[r][c]:
                c+=1; continue
            w=1
            while c+w<cols and g[r][c+w]: w+=1
            h=1
            while r+h<rows and all(g[r+h][cc] for cc in range(c,c+w)): h+=1
            for rr in range(r,r+h):
                for cc in range(c,c+w): g[rr][cc]=False
            blocks.append((r,c,h,w)); c+=w
    return blocks

def neighbors_passages(g, r, c):
    R,C=len(g),len(g[0])
    for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr,cc=r+dr,c+dc
        if 0<=rr<R and 0<=cc<C and not g[rr][cc]:
            yield rr,cc,dr,dc

def clearance_score(g):
    R,C=len(g),len(g[0])
    s=[[0]*C for _ in range(R)]
    for r in range(R):
        for c in range(C):
            if g[r][c]: continue
            walls=0
            for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
                rr,cc=r+dr,c+dc
                if 0<=rr<R and 0<=cc<C and g[rr][cc]: walls+=1
            s[r][c]=walls  # 0 open, 4 tight
    return s

def manhattan(a,b): return abs(a[0]-b[0])+abs(a[1]-b[1])

# -------- basic Dijkstra (no overlap logic) with optional forbidden set --------
def dijkstra_cost(g, start, goal, params, forbidden=None):
    """Plain Dijkstra with step/turn/alley costs; 'forbidden' cells are treated as walls."""
    R,C=len(g),len(g[0]); clr=clearance_score(g)
    forbidden = forbidden or set()
    step=params.get('step',1.0); tau=params.get('turn',0.0); alley=params.get('alley',0.0)
    INF=10**12; dist={}; prev={}; pq=[]
    s=(start[0],start[1],(0,0))
    dist[s]=0.0; heappush(pq,(0.0,s))
    def w_cost(pi,drdc,rr,cc):
        turn = tau if (pi!=(0,0) and pi!=drdc) else 0.0
        tight = clr[rr][cc]/4.0
        return max(0.0, step + turn + alley*tight)
    while pq:
        d, st = heappop(pq)
        if d!=dist.get(st,INF): continue
        r,c,pi=st
        if (r,c)==goal:
            path=[]; cur=st
            while cur in prev:
                (rr,cc,_), p = cur, prev[cur]
                path.append((rr,cc)); cur=p
            (rr,cc,_)=cur; path.append((rr,cc)); return path[::-1]
        for rr,cc,dr,dc in neighbors_passages(g,r,c):
            if (rr,cc) in forbidden: continue
            wc=w_cost(pi,(dr,dc),rr,cc); nd=d+wc
            ns=(rr,cc,(dr,dc))
            if nd<dist.get(ns,INF):
                dist[ns]=nd; prev[ns]=st; heappush(pq,(nd,ns))
    return []

# -------- resolver: enforce ≤1 overlap per prior path (pairwise) --------
def resolve_pairwise_overlap(path_cells, prior_paths, start, goal, rng):
    """
    Given a candidate path (set of cells) and prior path sets,
    return a forbidden set that blocks all but one overlapping tile per prior path.
    If all pairwise overlaps are already ≤1, returns empty set.
    """
    F=set()
    for P in prior_paths:
        inter = (path_cells & P) - {start,goal}
        if len(inter) <= 1:
            continue
        # keep exactly one overlap with this prior path, block the rest
        keep = rng.choice(list(inter))
        F |= (inter - {keep})
    return F

def find_path_pairwise(g, start, goal, params, prior_paths, rng, max_retries=32):
    """
    Try to find a path that satisfies:
      for every prior path P: |(path ∩ P) - {s,g}| ≤ 1
    Loop: plan path, analyze overlaps, block extras, re-plan.
    """
    F=set()
    for _ in range(max_retries):
        path = dijkstra_cost(g, start, goal, params, forbidden=F)
        if not path: return []  # blocked beyond repair
        S=set(path)
        extra = resolve_pairwise_overlap(S, prior_paths, start, goal, rng)
        if not extra:
            return path
        F |= extra
    return []  # gave up

# (Optional) Experiential variant using randomized greedy + the same resolver loop
def experiential_pairwise(g, start, goal, trials, rng, prior_paths, max_retries=24):
    R,C=len(g),len(g[0]); clr=clearance_score(g)
    def reachable(snode, blocked):
        if snode in blocked or goal in blocked: return False
        Q=deque([snode]); seen={snode}
        while Q:
            v=Q.popleft()
            if v==goal: return True
            r,c=v
            for rr,cc,_,_ in neighbors_passages(g,r,c):
                if (rr,cc) not in seen and (rr,cc) not in blocked:
                    seen.add((rr,cc)); Q.append((rr,cc))
        return False

    F=set()
    for _ in range(max_retries):
        best=None
        for _t in range(trials):
            path=[start]; visited={start}; prev_dir=None
            while path[-1]!=goal:
                r,c=path[-1]; cand=[]
                for rr,cc,dr,dc in neighbors_passages(g,r,c):
                    if (rr,cc) in visited or (rr,cc) in F: continue
                    blocked=visited.copy(); blocked.add((rr,cc))
                    if not reachable((rr,cc), blocked - {(rr,cc)}): continue
                    turn = 1.0 if (prev_dir is not None and prev_dir!=(dr,dc)) else 0.0
                    open_bonus = 1.0 - (clr[rr][cc]/4.0)
                    dgoal = manhattan((rr,cc), goal)
                    score = (-1.3*turn) + (-0.9*open_bonus) + (-0.7*dgoal) + rng.random()*0.05
                    cand.append(((rr,cc,dr,dc), score))
                if not cand: break
                cand.sort(key=lambda x:x[1])
                pick = rng.choice(cand[:min(3,len(cand))])[0]
                rr,cc,dr,dc=pick
                prev_dir=(dr,dc); path.append((rr,cc)); visited.add((rr,cc))
            if path and path[-1]==goal and ((best is None) or (len(path)>len(best))):
                best=path
        if not best: return []
        S=set(best)
        extra = resolve_pairwise_overlap(S, prior_paths, start, goal, rng)
        if not extra:
            return best
        F |= extra
    return []

# -------- drawing helpers --------
def draw_tiles_for_path(name_prefix, path, color, geom, skip_cells):
    cell_w,cell_h,off_x,off_y,tile_xy,tile_h,tile_z = geom
    mat = ensure_mat(f"{name_prefix}_Mat", color)
    col = get_collection("maze_paths")
    for i, rc in enumerate(path):
        if rc in skip_cells: continue
        x,y = rc_to_world(off_x, off_y, cell_w, cell_h, rc)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x,y,0.0))
        ob=bpy.context.active_object
        ob.name=f"{name_prefix}_{i:04d}"
        ob.dimensions=(tile_xy, tile_xy, tile_h)
        sit_on_ground(ob); ob.location.z += tile_z
        if ob.data.materials: ob.data.materials[0]=mat
        else: ob.data.materials.append(mat)
        link_exclusive(ob, col)

def draw_tiles_for_cells(name_prefix, cells, color, geom):
    cell_w,cell_h,off_x,off_y,tile_xy,tile_h,tile_z = geom
    mat = ensure_mat(f"{name_prefix}_Mat", color)
    col = get_collection("maze_paths")
    for i, rc in enumerate(sorted(cells)):
        x,y = rc_to_world(off_x, off_y, cell_w, cell_h, rc)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x,y,0.0))
        ob=bpy.context.active_object
        ob.name=f"{name_prefix}_{i:04d}"
        ob.dimensions=(tile_xy, tile_xy, tile_h)
        sit_on_ground(ob); ob.location.z += (tile_z + 0.002)  # slight lift
        if ob.data.materials: ob.data.materials[0]=mat
        else: ob.data.materials.append(mat)
        link_exclusive(ob, col)

# -------- properties --------
class MMM_Props(PropertyGroup):
    # Maze & seed
    rows: IntProperty(name="Rows", default=22, min=5, soft_max=300)
    cols: IntProperty(name="Cols", default=34, min=5, soft_max=300)
    randomize: BoolProperty(name="Random Seed", default=True)
    seed: IntProperty(name="Seed", default=12345, min=0)

    # Geometry
    cell_w: FloatProperty(name="Cell W", default=2.5, min=0.05)
    cell_h: FloatProperty(name="Cell H", default=2.5, min=0.05)
    height_min: FloatProperty(name="Wall H min", default=7.0, min=0.05)
    height_max: FloatProperty(name="Wall H max", default=20.0, min=0.05)
    uniform_height: BoolProperty(name="Uniform Height", default=False)

    # Loops / DE guard
    extra_loop_ratio: FloatProperty(name="Loop Ratio", default=0.06, min=0.0, max=1.0)
    keep_deadend_min_ratio: FloatProperty(name="Min Dead-End Ratio", default=0.06, min=0.0, max=1.0)
    keep_deadend_min_count: IntProperty(name="Min Dead-End Count", default=6, min=0)

    # Materials
    wall_color: FloatVectorProperty(name="Wall Color", subtype='COLOR', size=4, default=(1,1,1,1))
    wall_mat_name: StringProperty(name="Wall Mat", default="MazeWall")
    floor_mat_name: StringProperty(name="Floor Mat", default="MazeFloor")

    make_floor: BoolProperty(name="Make Floor", default=True)
    floor_thickness: FloatProperty(name="Floor Thickness", default=0.2, min=0.0)

    # Path tiles
    tile_size: FloatProperty(name="Path Tile Size", default=0.90, min=0.1, max=1.5)
    tile_height: FloatProperty(name="Path Tile Height", default=0.05, min=0.005)
    tile_z_offset: FloatProperty(name="Path Z Offset", default=0.03, min=0.0)

    # Colors
    start_color: FloatVectorProperty(name="Start Color", subtype='COLOR', size=4, default=(1.0,0.25,0.25,1.0))
    col_purist: FloatVectorProperty(name="Purist", subtype='COLOR', size=4, default=(0.2,0.7,1.0,1))
    col_cautious: FloatVectorProperty(name="Cautious", subtype='COLOR', size=4, default=(1.0,0.5,0.2,1))
    col_utilitarian: FloatVectorProperty(name="Utilitarian", subtype='COLOR', size=4, default=(0.3,1.0,0.5,1))
    col_experiential: FloatVectorProperty(name="Experiential", subtype='COLOR', size=4, default=(1.0,0.85,0.2,1))
    col_faith: FloatVectorProperty(name="Faith", subtype='COLOR', size=4, default=(0.9,0.6,1.0,1))
    col_intersection: FloatVectorProperty(name="Intersection", subtype='COLOR', size=4, default=(0.7,0.2,0.2,1))

    # Styles
    use_purist:      BoolProperty(name="Purist", default=True)
    use_cautious:    BoolProperty(name="Cautious", default=True)
    use_utilitarian: BoolProperty(name="Utilitarian", default=True)
    use_experiential:BoolProperty(name="Experiential", default=True)
    use_faith:       BoolProperty(name="Faith", default=False)

    experiential_trials: IntProperty(name="Experiential Trials", default=700, min=100, soft_max=5000)

    # Build behavior
    append_paths: BoolProperty(
        name="Append (Keep Existing Paths)",
        default=True,
        description="If ON, new paths are added to existing cached paths and overlays. If OFF, previous paths are cleared."
    )

# -------- operators --------
class MMM_OT_Generate(Operator):
    bl_idname = "mmm.generate"
    bl_label = "Generate Maze (Walls + Floor)"

    def execute(self, context):
        p=context.scene.mmm_props
        rng = random.Random(None if p.randomize else p.seed)
        maze_col = get_collection("maze"); paths_col=get_collection("maze_paths")
        clear_collection(maze_col); clear_collection(paths_col)

        # Build bitmap once and cache exactly
        bitmap, H, W, s_open, e_open = prims_maze(p.rows, p.cols, rng)

        # Dead-end aware loop carver (inline to keep determinism)
        def count_passages_and_deadends(grid):
            rows, cols = len(grid), len(grid[0]); passages=0; dead=0
            for r in range(1,rows-1):
                for c in range(1,cols-1):
                    if not grid[r][c]:
                        passages+=1; deg=0
                        for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
                            rr,cc=r+dr,c+dc
                            if 0<=rr<rows and 0<=cc<cols and not grid[rr][cc]: deg+=1
                        if deg==1: dead+=1
            return passages, dead

        def carve_loops_with_deadend_guard(grid, H, W, rng, ratio, min_deadend_ratio, min_deadend_abs):
            if ratio<=0: return
            cand=[]
            for r in range(1,H-1):
                for c in range(1,W-1):
                    if grid[r][c]:
                        if r%2==1 and c%2==0 and (not grid[r][c-1]) and (not grid[r][c+1]): cand.append((r,c))
                        if r%2==0 and c%2==1 and (not grid[r-1][c]) and (not grid[r+1][c]): cand.append((r,c))
            rng.shuffle(cand)
            max_to=int(len(cand)*ratio)
            total,_ = count_passages_and_deadends(grid)
            min_dead = max(min_deadend_abs, math.ceil(total*min_deadend_ratio))
            carved=0
            for (r,c) in cand:
                if carved>=max_to: break
                grid[r][c]=False
                _, dead_after = count_passages_and_deadends(grid)
                if dead_after>=min_dead: carved+=1
                else: grid[r][c]=True

        carve_loops_with_deadend_guard(bitmap, H, W, rng,
                                       p.extra_loop_ratio,
                                       p.keep_deadend_min_ratio,
                                       p.keep_deadend_min_count)

        start = inward(s_open, H, W); end = inward(e_open, H, W)

        total_w, total_h = W*p.cell_w, H*p.cell_h
        off_x, off_y = -total_w/2 + p.cell_w/2, -total_h/2 + p.cell_h/2

        # Walls
        wall_mat = ensure_mat(p.wall_mat_name, tuple(p.wall_color))
        blocks = merge_rectangles(bitmap, H, W)
        for (r,c,h,w) in blocks:
            sx, sy = w*p.cell_w, h*p.cell_h
            sz = (p.height_max if p.uniform_height else random.uniform(p.height_min, p.height_max))
            cx = off_x + c*p.cell_w + (w-1)*p.cell_w/2
            cy = -(off_y + r*p.cell_h + (h-1)*p.cell_h/2)
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, 0.0))
            ob=bpy.context.active_object; ob.name=f"MazeWall_{r}_{c}_{h}x{w}"
            ob.dimensions=(sx,sy,sz); sit_on_ground(ob)
            if ob.data.materials: ob.data.materials[0]=wall_mat
            else: ob.data.materials.append(wall_mat)
            link_exclusive(ob, maze_col)

        # Floor
        if p.make_floor:
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
            floor=bpy.context.active_object; floor.name="MazeFloor"
            floor.dimensions=(total_w + p.cell_w, total_h + p.cell_h, p.floor_thickness)
            sit_on_ground(floor)
            floor_mat = ensure_mat(p.floor_mat_name, (0.14,0.14,0.16,1))
            if floor.data.materials: floor.data.materials[0]=floor_mat
            else: floor.data.materials.append(floor_mat)
            link_exclusive(floor, maze_col)

        # Cache bitmap & placements and reset path cache
        context.scene["mmm_cache"] = {
            "bitmap": copy.deepcopy(bitmap),
            "rows": H, "cols": W,
            "start": start, "end": end,
            "off_x": off_x, "off_y": off_y,
            "cell_w": p.cell_w, "cell_h": p.cell_h,
            "paths": []  # list of {"key": str, "cells": [(r,c), ...]}
        }
        # Clear overlays
        clear_collection(get_collection("maze_paths"))
        self.report({'INFO'}, f"Maze {H}x{W} generated & cached.")
        return {'FINISHED'}

class MMM_OT_BuildPaths(Operator):
    bl_idname = "mmm.build_paths"
    bl_label = "Build Floor Paths (Styles)"

    def execute(self, context):
        p=context.scene.mmm_props
        cache=context.scene.get("mmm_cache")
        if not cache:
            self.report({'WARNING'}, "Generate the maze first."); return {'CANCELLED'}

        bitmap = cache["bitmap"]
        rows, cols = cache["rows"], cache["cols"]
        start, end = tuple(cache["start"]), tuple(cache["end"])
        off_x, off_y, cell_w, cell_h = cache["off_x"], cache["off_y"], cache["cell_w"], cache["cell_h"]

        # Path style definitions
        styles=[]
        if p.use_purist:      styles.append(("PURIST",      dict(step=1.0, turn=0.0, alley=0.0), "DIJKSTRA", tuple(p.col_purist)))
        if p.use_cautious:    styles.append(("CAUTIOUS",    dict(step=1.0, turn=0.6, alley=0.0), "DIJKSTRA", tuple(p.col_cautious)))
        if p.use_utilitarian: styles.append(("UTILITARIAN", dict(step=1.0, turn=0.2, alley=0.8), "DIJKSTRA", tuple(p.col_utilitarian)))
        if p.use_experiential:styles.append(("EXPERIENTIAL",{},                                   "MEANDER",  tuple(p.col_experiential)))
        if p.use_faith:       styles.append(("FAITH",       dict(step=1.0, turn=0.1, alley=0.2), "DIJKSTRA", tuple(p.col_faith)))

        rng = random.Random(None if p.randomize else p.seed)

        # Start from existing cache or reset (Append vs Replace)
        if p.append_paths:
            existing = cache.get("paths", [])
        else:
            existing = []
            cache["paths"] = []
            clear_collection(get_collection("maze_paths"))

        # Ensure start tile exists (if replacing we'll recreate; if appending, only add if missing)
        paths_col=get_collection("maze_paths")
        if (not p.append_paths) or (not any(o.name=="StartTile" for o in paths_col.objects)):
            sx,sy = rc_to_world(off_x, off_y, cell_w, cell_h, start)
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(sx,sy,0.0))
            st=bpy.context.active_object; st.name="StartTile"
            st.dimensions=(p.tile_size, p.tile_size, p.tile_height)
            sit_on_ground(st); st.location.z += p.tile_z_offset
            sm=ensure_mat("StartColor", tuple(p.start_color))
            if st.data.materials: st.data.materials[0]=sm
            else: st.data.materials.append(sm)
            link_exclusive(st, paths_col)

        # Build a list of prior path sets (for pairwise constraint)
        prior_sets=[set(tuple(rc) for rc in ent["cells"]) for ent in existing]

        # Solve & append
        built=0
        for (key, params, algo, color) in styles:
            # Give unique tag if appending same style multiple times
            tag = f"{key}#{sum(1 for e in existing if e['key'].startswith(key))+1}" if p.append_paths else key

            if algo=="DIJKSTRA":
                path = find_path_pairwise(bitmap, start, end, params, prior_sets, rng, max_retries=48)
            else:
                path = experiential_pairwise(bitmap, start, end, p.experiential_trials, rng, prior_sets, max_retries=24)

            if not path:
                print(f"[{tag}] no valid path under pairwise ≤1 rule; skipped.")
                continue

            existing.append({"key": tag, "cells": [tuple(rc) for rc in path]})
            prior_sets.append(set(path))
            built += 1

        cache["paths"] = existing  # persist

        # ---- draw everything (clean redraw, but only paths/intersections; keep start tile) ----
        # Remove old Path_* and Path_Intersections_* tiles; keep StartTile
        clear_collection(paths_col, name_prefixes=("Path_", "Path_Intersections_"))

        # Intersections across ALL cached paths (exclude start/end)
        counts=Counter()
        for ent in existing:
            for rc in ent["cells"]:
                if rc!=start and rc!=end:
                    counts[tuple(rc)] += 1
        overlap_cells = {rc for rc,n in counts.items() if n>=2}

        geom=(cell_w,cell_h,off_x,off_y,p.tile_size,p.tile_height,p.tile_z_offset)

        # Draw each cached path, skipping overlaps (so intersections are clean)
        style_color_map = {
            "PURIST": tuple(p.col_purist),
            "CAUTIOUS": tuple(p.col_cautious),
            "UTILITARIAN": tuple(p.col_utilitarian),
            "EXPERIENTIAL": tuple(p.col_experiential),
            "FAITH": tuple(p.col_faith),
        }
        for ent in existing:
            base = ent["key"].split("#")[0]
            color = style_color_map.get(base, (0.8,0.8,0.8,1))
            draw_tiles_for_path(f"Path_{ent['key']}", ent["cells"], color, geom, skip_cells=overlap_cells)

        # Draw intersections once
        if overlap_cells:
            draw_tiles_for_cells("Path_Intersections", overlap_cells, tuple(p.col_intersection), geom)

        context.scene["mmm_cache"] = cache
        self.report({'INFO'}, f"Added {built} path(s). Total paths: {len(existing)}. Intersections: {len(overlap_cells)}.")
        return {'FINISHED'}

class MMM_OT_ClearPaths(Operator):
    bl_idname = "mmm.clear_paths"
    bl_label = "Clear Paths Only"
    def execute(self, context):
        paths_col = get_collection("maze_paths")
        clear_collection(paths_col)
        cache=context.scene.get("mmm_cache")
        if cache and "paths" in cache:
            cache["paths"]=[]
            context.scene["mmm_cache"]=cache
        self.report({'INFO'}, "Cleared all path overlays & cache.")
        return {'FINISHED'}

class MMM_OT_Export(Operator):
    bl_idname = "mmm.export"
    bl_label = "Export (OBJ/FBX/GLB)"
    export_format: EnumProperty(
        name="Format",
        items=[('OBJ',"OBJ","Wavefront OBJ"),('FBX',"FBX","Autodesk FBX"),('GLB',"GLB","glTF Binary")],
        default='GLB'
    )
    include_paths: BoolProperty(name="Include Paths", default=True)
    join_mode: EnumProperty(
        name="Mode",
        items=[('SEPARATE',"Separate Objects","Export each object"),
               ('MERGED',"Single Mesh","Export a temporary joined mesh")],
        default='SEPARATE'
    )
    filepath: StringProperty(name="File Path", subtype='FILE_PATH')

    def invoke(self, context, event):
        ext={ 'OBJ':".obj",'FBX':".fbx",'GLB':".glb"}[self.export_format]
        if not self.filepath: self.filepath=bpy.path.abspath(f"//maze{ext}")
        context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}

    def execute(self, context):
        def select_only(objs):
            bpy.ops.object.select_all(action='DESELECT')
            for o in objs:
                try: o.select_set(True)
                except: pass
            if objs: bpy.context.view_layer.objects.active = objs[0]

        objs=[]
        maze_col=get_collection("maze"); objs += [o for o in maze_col.objects if o.type=='MESH']
        if self.include_paths:
            paths_col=get_collection("maze_paths"); objs += [o for o in paths_col.objects if o.type=='MESH']
        if not objs:
            self.report({'WARNING'},"Nothing to export."); return {'CANCELLED'}

        temp=None; export_set=objs
        if self.join_mode=='MERGED':
            select_only(objs); bpy.ops.object.duplicate()
            dups=[o for o in bpy.context.view_layer.objects if o.select_get()]
            if not dups: self.report({'WARNING'}, "Duplication failed."); return {'CANCELLED'}
            bpy.context.view_layer.objects.active=dups[0]
            try: bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            except: pass
            bpy.ops.object.join(); temp=bpy.context.view_layer.objects.active
            temp.name="MazeExport_Temp"; link_exclusive(temp, maze_col); export_set=[temp]
        select_only(export_set)
        fp=bpy.path.abspath(self.filepath); os.makedirs(os.path.dirname(fp), exist_ok=True)
        try:
            if self.export_format=='OBJ': bpy.ops.wm.obj_export(filepath=fp, export_selected_objects=True)
            elif self.export_format=='FBX': bpy.ops.export_scene.fbx(filepath=fp, use_selection=True, apply_scale_options='FBX_SCALE_NONE')
            elif self.export_format=='GLB': bpy.ops.export_scene.gltf(filepath=fp, export_format='GLB', use_selection=True)
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {e}")
            if temp: select_only([temp]); bpy.ops.object.delete()
            return {'CANCELLED'}
        if temp: select_only([temp]); bpy.ops.object.delete()
        self.report({'INFO'}, f"Exported to {fp}")
        return {'FINISHED'}

# -------- UI --------
class MMM_PropUI(Panel):
    bl_label = "Mo's Maze Maker"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mo's Maze Maker"
    def draw(self, context):
        p=context.scene.mmm_props; L=self.layout
        box=L.box(); box.label(text="Maze Size & Seed")
        row=box.row(align=True); row.prop(p,"rows"); row.prop(p,"cols")
        row=box.row(align=True); row.prop(p,"randomize"); 
        if not p.randomize: row.prop(p,"seed")

        box=L.box(); box.label(text="Geometry & Floor")
        row=box.row(align=True); row.prop(p,"cell_w"); row.prop(p,"cell_h")
        row=box.row(align=True); row.prop(p,"height_min"); row.prop(p,"height_max")
        box.prop(p,"uniform_height")
        row=box.row(align=True); row.prop(p,"make_floor"); row.prop(p,"floor_thickness")

        box=L.box(); box.label(text="Loops & Dead-Ends")
        box.prop(p,"extra_loop_ratio")
        row=box.row(align=True); row.prop(p,"keep_deadend_min_ratio"); row.prop(p,"keep_deadend_min_count")

        box=L.box(); box.label(text="Materials")
        row=box.row(align=True); row.prop(p,"wall_color"); box.prop(p,"wall_mat_name")
        box.prop(p,"floor_mat_name")
        L.operator("mmm.generate", icon='MESH_CUBE', text="Generate Maze (Walls + Floor)")

        L.separator()
        box=L.box(); box.label(text="Path Tiles")
        row=box.row(align=True); row.prop(p,"tile_size"); row.prop(p,"tile_height"); row.prop(p,"tile_z_offset")
        row=box.row(align=True); row.prop(p,"start_color"); row.prop(p,"col_intersection")
        box=L.box(); box.label(text="Styles & Colors")
        row=box.row(align=True); row.prop(p,"use_purist");      row.prop(p,"col_purist")
        row=box.row(align=True); row.prop(p,"use_cautious");    row.prop(p,"col_cautious")
        row=box.row(align=True); row.prop(p,"use_utilitarian"); row.prop(p,"col_utilitarian")
        row=box.row(align=True); row.prop(p,"use_experiential");row.prop(p,"col_experiential")
        row=box.row(align=True); row.prop(p,"use_faith");       row.prop(p,"col_faith")
        box=L.box(); box.prop(p,"experiential_trials")
        box.prop(p,"append_paths")
        L.operator("mmm.build_paths", icon='MOD_BUILD', text="Build Floor Paths (Styles)")
        L.operator("mmm.clear_paths", icon='TRASH', text="Clear Paths Only")

        L.separator()
        box=L.box(); box.label(text="Export")
        box.operator("mmm.export", icon='EXPORT', text="Export (OBJ/FBX/GLB)")

# -------- register --------
classes=(MMM_Props, MMM_OT_Generate, MMM_OT_BuildPaths, MMM_OT_ClearPaths, MMM_OT_Export, MMM_PropUI)
def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.mmm_props = PointerProperty(type=MMM_Props)
def unregister():
    del bpy.types.Scene.mmm_props
    for c in reversed(classes): bpy.utils.unregister_class(c)
if __name__=="__main__":
    register()
