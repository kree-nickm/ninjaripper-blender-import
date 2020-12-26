import bpy
import bmesh
import mathutils
import hashlib
import time

class RipMesh:
   def __init__(self, ripFile):
      self.ripFile = ripFile
      self.mesh = bpy.data.meshes.new(self.ripFile.fileLabel + "Mesh")
      self.object = bpy.data.objects.new(self.ripFile.fileLabel, self.mesh)
   
   def loadRip(self):
      loadStart = time.process_time()
      self.bmesh = bmesh.new()
      self.bmesh.from_mesh(self.mesh)
      bpy.context.collection.objects.link(self.object)
      bpy.context.view_layer.objects.active = self.object
      bpy.ops.object.mode_set(mode='EDIT', toggle=False)
      positions = None
      normals = None
      uvs = []
      for sem in self.ripFile.semantics:
         if sem['nameUpper'] == "POSITION" and positions is None:
            positions = sem
         if sem['nameUpper'] == "NORMAL" and normals is None:
            normals = sem
         if sem['nameUpper'] == "TEXCOORD":
            uvs.append((sem, self.bmesh.loops.layers.uv.new()))
      
      for vert in self.ripFile.vertexes:
         vtx = self.bmesh.verts.new(vert[positions['label']])
         vtx.normal = mathutils.Vector(vert[normals['label']][0:3]) # I've seen rips with 4-dimensional normals, no idea what the deal is with that
         
      self.bmesh.verts.ensure_lookup_table()
      for f in self.ripFile.faces:
         try:
            face = self.bmesh.faces.new((self.bmesh.verts[f[0]], self.bmesh.verts[f[1]], self.bmesh.verts[f[2]]))
            face.smooth = True
            face.material_index = 0
            
            for uv_set_loop in range(3):
               for z in range(len(uvs)):
                  face.loops[uv_set_loop][uvs[z][1]].uv = self.ripFile.vertexes[f[uv_set_loop]][uvs[z][0]['label']]
         except Exception as e:
            print(str(e))
      bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
      self.bmesh.to_mesh(self.mesh)
      self.bmesh.free()
      # Toggling seems to fix weird mesh appearance in some cases.
      bpy.ops.object.mode_set(mode='EDIT', toggle=False)
      bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
      loadTime = time.process_time() - loadStart
      print("{}: RIP load took {}s".format(self.ripFile.fileLabel, loadTime))
      return self.mesh
   
   def loadMaterial(self, reuseMats=True, importShaders=False):
      self.material = None
      if len(self.ripFile.textures) > 0:
         texStr = ""
         for t in self.ripFile.textures:
            texStr += t['fileName']
         materialName = hashlib.md5(texStr.encode()).hexdigest()
      else:
         materialName = None
      
      if materialName is not None and materialName in bpy.data.materials and reuseMats:
         self.material = bpy.data.materials[materialName]
      elif materialName is not None:
         self.material = bpy.data.materials.new(name=materialName)
         self.material.use_nodes = True
         if importShaders:
            for shader in self.ripFile.shaders:
               pass
         else:
            for t in range(len(self.ripFile.textures)):
               tex = self.material.node_tree.nodes.new('ShaderNodeTexImage')
               tex.image = bpy.data.images.load(self.ripFile.textures[t]['filePath'], check_existing=True)
               tex.image.colorspace_settings.is_data = True
               tex.image.colorspace_settings.name = "Non-Color"
               tex.hide = True
               tex.location = [-300, -50*t]
      
      if self.material is not None:
         self.object.data.materials.append(self.material)
      return self.material
   
   def delete(self):
      bpy.data.objects.remove(self.object)
      bpy.data.meshes.remove(self.mesh)
