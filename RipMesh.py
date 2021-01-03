import bpy
import bmesh
import mathutils
import hashlib
import time
from math import floor

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
               if shader.shaderType == 1:
                  self.loadShader(shader)
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
   
   def loadShader(self, shader):
      shader.parse()
      loadStart = time.process_time()
      bsdf = self.material.node_tree.nodes["Principled BSDF"]
      
      i = 0
      for ripNode in shader.nodes:
         node = self.createShaderNode(ripNode)
         x = -2000 + 600 * floor(i / 100)
         y = 1000 - 40 * (i % 100)
         node.location = [x,y]
         i += 1
         
      x = -2000 + 600 * floor(i / 100)
      y = 1000 - 40 * (i % 100)
      bsdf.location = [x,y]
      
      basecolor = self.material.node_tree.nodes.new("ShaderNodeCombineRGB")
      basecolor.hide = True
      basecolor.location = [bsdf.location[0]-170, bsdf.location[1]-100]
      self.material.node_tree.links.new(bsdf.inputs['Base Color'], basecolor.outputs[0])
      self.material.node_tree.links.new(bsdf.inputs['Subsurface Color'], basecolor.outputs[0])
      self.createNodeChain(shader.registers['o1']['x'], basecolor, 0)
      self.createNodeChain(shader.registers['o1']['y'], basecolor, 1)
      self.createNodeChain(shader.registers['o1']['z'], basecolor, 2)
      
      rro1w = self.material.node_tree.nodes.new("NodeReroute")
      rro1w.location = [bsdf.location[0]-80, bsdf.location[1]-140]
      self.createNodeChain(shader.registers['o1']['w'], rro1w, 0)
      
      rro3x = self.material.node_tree.nodes.new("NodeReroute")
      rro3x.location = [bsdf.location[0]-80, bsdf.location[1]-180]
      self.createNodeChain(shader.registers['o3']['x'], rro3x, 0)
      self.material.node_tree.links.new(bsdf.inputs['Subsurface'], rro3x.outputs[0])
      
      sssradius = self.material.node_tree.nodes.new("ShaderNodeCombineXYZ")
      sssradius.hide = True
      sssradius.location = [bsdf.location[0]-170, bsdf.location[1]-220]
      self.material.node_tree.links.new(bsdf.inputs['Subsurface Radius'], sssradius.outputs[0])
      self.createNodeChain(shader.registers['o3']['y'], sssradius, 0)
      self.createNodeChain(shader.registers['o3']['z'], sssradius, 1)
      self.createNodeChain(shader.registers['o3']['w'], sssradius, 2)
      
      rro2x = self.material.node_tree.nodes.new("NodeReroute")
      rro2y = self.material.node_tree.nodes.new("NodeReroute")
      rro2z = self.material.node_tree.nodes.new("NodeReroute")
      rro2w = self.material.node_tree.nodes.new("NodeReroute")
      rro2x.location = [bsdf.location[0]-80, bsdf.location[1]-260]
      rro2y.location = [bsdf.location[0]-80, bsdf.location[1]-300]
      rro2z.location = [bsdf.location[0]-80, bsdf.location[1]-340]
      rro2w.location = [bsdf.location[0]-80, bsdf.location[1]-380]
      self.createNodeChain(shader.registers['o2']['x'], rro2x, 0)
      self.createNodeChain(shader.registers['o2']['y'], rro2y, 0)
      self.createNodeChain(shader.registers['o2']['z'], rro2z, 0)
      self.createNodeChain(shader.registers['o2']['w'], rro2w, 0)
      self.material.node_tree.links.new(bsdf.inputs['Roughness'], rro2x.outputs[0])
      self.material.node_tree.links.new(bsdf.inputs['Specular'], rro2y.outputs[0])
      self.material.node_tree.links.new(bsdf.inputs['Metallic'], rro2z.outputs[0])
      
      normal = self.material.node_tree.nodes.new("ShaderNodeNormalMap")
      normal.hide = True
      normal.location = [bsdf.location[0]-170, bsdf.location[1]-515]
      self.material.node_tree.links.new(bsdf.inputs['Normal'], normal.outputs[0])
      normalcolor = self.material.node_tree.nodes.new("ShaderNodeCombineXYZ")
      normalcolor.hide = True
      normalcolor.location = [bsdf.location[0]-270, bsdf.location[1]-515]
      self.material.node_tree.links.new(normal.inputs['Color'], normalcolor.outputs[0])
      self.createNodeChain(shader.registers['o0']['x'], normalcolor, 0)
      self.createNodeChain(shader.registers['o0']['y'], normalcolor, 1)
      
      rro0z = self.material.node_tree.nodes.new("NodeReroute")
      rro0w = self.material.node_tree.nodes.new("NodeReroute")
      rro0z.location = [bsdf.location[0]-80, bsdf.location[1]-555]
      rro0w.location = [bsdf.location[0]-80, bsdf.location[1]-595]
      self.createNodeChain(shader.registers['o0']['z'], rro0z, 0)
      self.createNodeChain(shader.registers['o0']['w'], rro0w, 0)
      
      loadTime = time.process_time() - loadStart
      print("{} ({}): Material creation took {}s".format(self.ripFile.fileLabel, shader.fileName, loadTime))
   
   def createNodeChain(self, ripNodeOutput, previousNode, inputId):
      '''Create the entire chain of nodes that ends with the given node.
      
      Parameters
      ----------
      ripNodeOutput : RipNodeOutput
         the simulated output that we need to create a node for and then connect to the input
      previousNode : bpy.types.ShaderNode
         the existing node who inputs we need to link
      inputId : int or str
         the id of the input of previousNode that we are creating a link for
      '''
      
      ripNode = ripNodeOutput.node
      if ripNode.blenderNode is None:
         createShaderNode(self, ripNode)
         ripNode.blenderNode.location = [previousNode.location[0]-170, previousNode.location[1]+int(inputId)*40]
      self.material.node_tree.links.new(previousNode.inputs[inputId], ripNode.blenderNode.outputs[ripNodeOutput.id])
      if not ripNode.handled:
         for id in ripNode.inputs:
            if ripNode.inputs[id].connection is not None:
               self.createNodeChain(ripNode.inputs[id].connection, ripNode.blenderNode, id)
            else:
               ripNode.blenderNode.inputs[id].default_value = ripNode.inputs[id].defaultValue
         ripNode.handled = True
   
   def createShaderNode(self, ripNode):
      ripNode.blenderNode = self.material.node_tree.nodes.new("ShaderNode"+ripNode.type)
      ripNode.blenderNode.hide = True
      for prop in ripNode.options:
         if prop in ['name','label','operation','use_clamp']:
            setattr(ripNode.blenderNode, prop, ripNode.options[prop])
      if "imageData" in ripNode.options:
         ripNode.blenderNode.image = bpy.data.images.load(ripNode.options['imageData']['filePath'], check_existing=True)
         ripNode.blenderNode.image.colorspace_settings.is_data = True
         ripNode.blenderNode.image.colorspace_settings.name = "Non-Color"
      return ripNode.blenderNode
   
   def delete(self):
      bpy.data.objects.remove(self.object)
      bpy.data.meshes.remove(self.mesh)
