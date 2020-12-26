import os
import re
import struct
from math import floor

class RipShader:
   cbRegEx = re.compile("//\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+);\s*//\s+Offset:\s+(\d+)\s+Size:\s+(\d+)")
   rRegEx = re.compile("//\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s+(\d+)\s+(\d+)")
   ioRegEx = re.compile("//\s+([a-zA-Z0-9_]+)\s+(\d+)\s+([xyzw]+)\s+(\d+)\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s+([xyzw]+)")
   dclxRegEx = re.compile("^x(\d+)\[(\d+)\] (\d+)")
   
   def __init__(self, fileDir, fileName, textures):
      self.fileDir = fileDir
      self.fileName = fileName
      self.filePath = os.path.join(fileDir, fileName)
      self.fileLabel, self.fileExt = os.path.splitext(self.fileName)
      if self.fileExt.upper() == ".VS":
         self.shaderType = 0
      elif self.fileExt.upper() == ".PS":
         self.shaderType = 1
      else:
         raise ValueError("File '{}' passed to RipShader is not a VS or PS file. ({})".format(self.fileName, self.fileExt))
      self.parsed = False
      self.textures = textures
      self.shaderVersion = ""
      self.globalFlags = []
   
   def parse(self):
      self.data = {
         'buffers': {
         },
         'resources': {
         },
         'input': {
         },
         'output': {
         }
      }
      self.registers = {}
      self.nodes = [] # RipNode instances will add themselves to this
      with open(self.filePath, 'r') as file:
         self.currentLine = 0
         self.currentBlock = {
            'name': None,
            'type': None,
            'status': 0
         }
         self.ignoring = False
         for line in file:
            self.currentLine += 1
            if line.startswith("//"):
               if self.currentBlock['status'] == 0:
                  if line.startswith("// cbuffer "):
                     self.currentBlock['name'] = line[11:].strip()
                     self.currentBlock['type'] = "cbuffer"
                     self.currentBlock['status'] = 1
                     
                  elif line.startswith("// Resource Bindings:"):
                     self.currentBlock['name'] = "resources"
                     self.currentBlock['type'] = "other"
                     self.currentBlock['status'] = 1
                     
                  elif line.startswith("// Input signature:"):
                     self.currentBlock['name'] = "input"
                     self.currentBlock['type'] = "other"
                     self.currentBlock['status'] = 1
                     
                  elif line.startswith("// Output signature:"):
                     self.currentBlock['name'] = "output"
                     self.currentBlock['type'] = "other"
                     self.currentBlock['status'] = 1
                     
               elif self.currentBlock['status'] == 1:
                  if self.currentBlock['type'] == "cbuffer" and line.startswith("// {"):
                     self.currentBlock['status'] = 2
                     self.data['buffers'][self.currentBlock['name']] = {}
                     
                  elif self.currentBlock['type'] == "other" and line.startswith("// Name"):
                     self.currentBlock['status'] = 2
                     
               elif self.currentBlock['status'] == 2:
                  if self.currentBlock['type'] == "cbuffer":
                     if line.startswith("// }"):
                        self.currentBlock['name'] = None
                        self.currentBlock['type'] = None
                        self.currentBlock['status'] = 0
                        
                     elif line.find("[unused]") == -1:
                        match = self.cbRegEx.search(line)
                        if match:
                           type, name, offset, size = match.group(1,2,3,4)
                           offset = int(int(offset)/4)
                           size = int(int(size)/4)
                           for x in range(offset, offset+size):
                              idx = str(int(x/4))
                              part = str("xyzw"[int(x%4)])
                              if idx in self.data['buffers'][self.currentBlock['name']]:
                                 self.data['buffers'][self.currentBlock['name']][idx][part] = {'name':name+"."+part, 'originalSize':size}
                              else:
                                 self.data['buffers'][self.currentBlock['name']][idx] = {part:{'name':name+"."+part, 'originalSize':size}}
                                 
                  elif self.currentBlock['type'] == "other":
                     if line.strip() == "//":
                        self.currentBlock['name'] = None
                        self.currentBlock['type'] = None
                        self.currentBlock['status'] = 0
                        
                     elif self.currentBlock['name'] == "resources":
                        match = self.rRegEx.search(line)
                        if match:
                           name, type, format, dim, slot, elements = match.group(1,2,3,4,5,6)
                           if type == "texture":
                              try:
                                 i = len(list(filter(lambda x:x[0]=="t", self.data['resources'])))
                                 self.data['resources']['t'+slot] = {'name':name, 'data':self.textures[i]}
                              except IndexError:
                                 print("Texture resource declaration '{}' exceeds the number of stored textures ({}/{}) (line {})".format(name, i, len(self.textures), self.currentLine))
                           elif type == "cbuffer":
                              try:
                                 self.data['resources']['cb'+slot] = {'name':name, 'data':self.data['buffers'][name]}
                              except IndexError:
                                 print("Buffer resource declaration refers to undefined buffer '{}' (line {})".format(name, self.currentLine))
                           elif type == "sampler":
                              self.data['resources']['s'+slot] = {'name':name}
                              
                     elif self.currentBlock['name'] == "input" or self.currentBlock['name'] == "output":
                        match = self.ioRegEx.search(line)
                        if match:
                           # If oDepthLE is present, it will be skipped, because it doesn't match the RegEx. However, it will still be handled in the ASM.
                           name, index, mask, register, sysvalue, format, used = match.group(1,2,3,4,5,6,7)
                           reg = 'v'+register if self.currentBlock['name']=="input" else 'o'+register
                           data = {'name':name, 'index':index}
                           for c in mask:
                              if reg in self.data[self.currentBlock['name']]:
                                 self.data[self.currentBlock['name']][reg][c] = data
                              else:
                                 self.data[self.currentBlock['name']][reg] = {c:data}
                           # input of .vs is the vertex data
                           # input of .ps is matched to the output of .vs
                           # (all of the below might only apply to BG3)
                           #  o0 seems to relate to the normal map
                           #  o1 looks like the RGB base colors, unsure what the 'w' component is (it's not alpha)
                           #  o2 seems to contain reflectance data
                           #  o3 might be subsurface data
            else:
               self.handleASM(line)
      self.parsed = True
   
   def handleASM(self, line):
      words = self.parseASM(line)
      if words[0] == "ret":
         return False
      elif words[0].startswith("vs_") or words[0].startswith("ps_"):
         self.shaderVersion = words[0]
      elif words[0] == "dcl_sampler":
         pass
         # Don't know what to do with these, probably nothing
         # Different samplers require different handling, but there's no way to automatically detect what
      elif words[0] == "dcl_globalFlags":
         self.globalFlags += words[1:]
      elif words[0] == "dcl_constantbuffer":
         if words[2] == "immediateIndexed":
            parts = words[1].split("[")
            if len(parts) > 1:
               for i in self.data['resources'][parts[0]]['data']:
                  for c in self.data['resources'][parts[0]]['data'][i]:
                     node = RipNode(self, "Value")
                     if parts[0] not in self.registers:
                        self.registers[parts[0]] = {}
                     if i not in self.registers[parts[0]]:
                        self.registers[parts[0]][i] = {}
                     self.registers[parts[0]][i][c] = node.output()
            else:
               print("Invalid constant buffer declaration {} (line {})".format(words[1], self.currentLine))
         else:
            print("Unsupported constant buffer access pattern {} (line {})".format(words[2], self.currentLine))
      elif words[0] == "dcl_resource_texture2d":
         texnode = RipNode(self, "TexImage")
         sepnode = RipNode(self, "SeparateRGB")
         texnode.options['imageData'] = self.data['resources'][words[2]]['data']
         texnode.options['name'] = self.data['resources'][words[2]]['name']
         texnode.options['label'] = self.data['resources'][words[2]]['name']
         texnode.output(0, sepnode.input())
         if words[2] not in self.registers:
            self.registers[words[2]] = {}
         self.registers[words[2]]['x'] = sepnode.output(0)
         self.registers[words[2]]['y'] = sepnode.output(1)
         self.registers[words[2]]['z'] = sepnode.output(2)
         self.registers[words[2]]['w'] = texnode.output(1)
      elif words[0] == "dcl_input" or words[0] == "dcl_input_ps":
         if words[0] == "dcl_input":
            parts = words[1].split(".")
         else:
            parts = words[2].split(".")
         if len(parts) > 1:
            for c in parts[1]:
               node = RipNode(self, "Value")
               if parts[0] not in self.registers:
                  self.registers[parts[0]] = {}
               self.registers[parts[0]][c] = node.output()
         else:
            node = RipNode(self, "Value")
            self.registers[parts[0]] = node.output()
      elif words[0] == "dcl_output":
         parts = words[1].split(".")
         if len(parts) > 1:
            for c in parts[1]:
               if parts[0] not in self.registers:
                  self.registers[parts[0]] = {}
               self.registers[parts[0]][c] = None
         else:
            self.registers[parts[0]] = None
      elif words[0] == "dcl_temps":
         for i in range(int(words[1])):
            self.registers['r'+str(i)] = {'x':None, 'y':None, 'z':None, 'w':None}
      elif words[0] == "if" or  words[0] == "if_nz" or  words[0] == "if_z":
         print("if statements currently unsupported (line {})".format(self.currentLine))
         self.ignoring = True
      elif words[0] == "endif":
         self.ignoring = False
      else:
         words[0] = self.parseASMInstruction(words[0])
         words[1] = self.parseASMDest(words[1])
         for i in range(2, len(words)):
            words[i] = self.parseASMSrc(words[i])
         #print(words)
         if words[0][0] == "sample_indexable":
            #TODO: Check for negative modifiers
            uvnode = RipNode(self, "CombineXYZ")
            uvnode.input(0, self.registers[words[2][0][1]][words[2][0][2]])
            uvnode.input(1, self.registers[words[2][1][1]][words[2][1][2]])
            texnode = self.registers[words[3][0][1]]['w'].node
            texnode.input(0, uvnode.output())
            texnode.options['sampler'] = self.data['resources'][words[4][0][1]]
            for c in words[1][1]:
               self.registers[words[1][0]]["xyzw"[c]] = self.registers[words[3][c][1]][words[3][c][2]]
         elif words[0][0] in RipNode.basicMaths:
            '''outputs = []
            for t in terms[0]:
               outputs.append(None)
            for r in regs['indexes']:
               if len(regs['indexes']) == 1:
                  s = 0
               else:
                  s = r
               loc = get_shader_location(data['nodeCount'])
               node = create_asm_node("Math", [loc[0]+10*s, loc[1]], [term[s] for term in terms], op, sat)
               data['nodeCount'] = data['nodeCount'] + 1
               outputs[s] = node.outputs[0]
            apply_asm_mask(regs, outputs)'''
            
            node = RipNode(self, "Math")
            node.options = RipNode.basicMaths[words[0][0]]
            node.options['use_clamp'] = (words[0][1] & 1 == 1)
         else:
            print("Unhandled ASM instruction \"{}\" (line {})".format(words[0], self.currentLine))
      return True
   
   def parseASM(self, line):
      """Parses a line of HLSL ASM into something this script can understand
      
      Parameters
      ----------
      line : str
         the ASM instruction line
      
      Returns
      -------
      list
         the ASM instruction split by terms
      """
      
      result = []
      subresult = []
      bStart = 0
      parins = 0
      isNumeric = False
      for c in range(len(line)):
         # If we aren't inside a parinthetical, then spaces, commas, and new-lines are word separators.
         if parins == 0 and (line[c] == " " or line[c] == "," or line[c] == "\n"):
            # Skip consecutive word separators (empty words)
            if c > bStart:
               result.append(line[bStart:c])
            bStart = c+1
            isNumeric = False
         # If we aren't inside a parinthetical, then "l" followed by "(" means we are about to read a list of numbers.
         elif parins == 0 and bStart == c and line[c] == "l" and line[c+1] == "(":
            bStart = c+1
            isNumeric = True
         elif line[c] == "(":
            parins += 1
            # We only really care if this is a list of numbers, otherwise treat this like any other word.
            if isNumeric:
               bStart = c+1
         # If we are inside a parinthetical, spaces, commas, and closing parins are separators.
         elif parins > 0 and (line[c] == " " or line[c] == "," or line[c] == ")"):
            if line[c] == ")":
               parins -= 1
            # We only really care if this is a list of numbers, otherwise treat this like any other word.
            if isNumeric:
               if c > bStart:
                  subresult.append(line[bStart:c])
               if line[c] == ")":
                  result.append(subresult)
                  subresult = []
               bStart = c+1
      # Just in case the line didn't end with a new-line
      if len(line) > bStart:
         result.append(line[bStart:])
      return result
   
   def parseASMInstruction(self, term):
      """Parses an ASM instruction name into something this script can understand
      
      Parameters
      ----------
      term : str
         the ASM instruction name
      
      Returns
      -------
      tuple
         a tuple with two elements:
            str, the unmodified instruction
            int, bitwise, modifiers of the instruction: 1=saturate
      """
      
      instruction = term.split("(")
      if instruction[0].endswith("_sat"):
         return (instruction[0][:-4], 1)
      else:
         return (instruction[0], 0)
   
   def parseASMDest(self, term):
      """Parses a dest term of an ASM instruction into something this script can understand
      
      Parameters
      ----------
      term : str
         a term of the ASM instruction
      
      Returns
      -------
      tuple
         a tuple with two elements:
            str or list[2], the destination register
               if str, its a normal register and this is the name
               if list[2], it's a indexed register, first element is the name, second is the index
            list, indexes of the destination components as given by the mask, or None if there was no mask
      """
      
      termParts = term.split(".")
      destParts = termParts[0].split("[")
      if len(destParts) > 1:
         destParts[1] = destParts[1][:-1]
         dest = destParts
      else:
         dest = termParts[0]
      if len(termParts) > 1:
         mask = []
         if termParts[1].find("x") > -1:
            mask.append(0)
         if termParts[1].find("y") > -1:
            mask.append(1)
         if termParts[1].find("z") > -1:
            mask.append(2)
         if termParts[1].find("w") > -1:
            mask.append(3)
      else:
         mask = None
      return (dest, mask)

   def parseASMSrc(self, term):
      """Parses a src term of an ASM instruction into something this script can understand
      
      Parameters
      ----------
      term : str
         a term of the ASM instruction
      
      Returns
      -------
      list
         a list of components to be used by the instruction, each element either a float or a tuple (see parseASMSwizzle)
      """
      
      if type(term) is list:
         for w in range(len(term)):
            if term[w].startswith("0x"):
               term[w] = struct.unpack('<f', struct.pack('<I', int(term[w], 0)))[0]
            else:
               term[w] = float(term[w])
         return term
      else:
         return self.parseASMSwizzle(term)
   
   def parseASMSwizzle(self, term):
      """Parses a single ASM instruction term with swizzle into something this script can understand
      
      Parameters
      ----------
      term : str
         a term of the ASM instruction
      
      Returns
      -------
      list
         a list of tuples, each with the following three elements:
            int, bitwise, representing whether the term had negative or absolute value symbols: 1=negative, 2=absolute
            str or list[2], the source register
               if str, its a normal register and this is the name
               if list[2], it's a indexed register, first element is the name, second is the index
            str, one of the components of this swizzle, or None if there was no swizzle
      """
      
      mod = 0
      if term.startswith("-"):
         mod += 1
         term = term[1:]
      if term.startswith("|"):
         mod += 2
         term = term[1:-1]
      termParts = term.split(".")
      srcParts = termParts[0].split("[")
      if len(termParts) > 1:
         result = []
         for n in termParts[1]:
            if len(srcParts) > 1:
               srcParts[1] = srcParts[1][:-1]
               result.append((mod, srcParts, n))
            else:
               result.append((mod, termParts[0], n))
         return result
      elif len(srcParts) > 1:
         return [(mod, srcParts, None)]
      else:
         return [(mod, termParts[0], None)]
   
   # Takes output from the above function and returns a list of the associated stored node outputs, ignoring modifier for now
   def parsed_swizzle_to_outputs(swizzle):
      result = []
      for term in swizzle:
         result.append(data[term[1]][term[2]])
      return result
   
   # Updates the data dict with the lastest outputs in the chain (src)
   def apply_asm_mask(regs, src):
      if type(regs['reg']) is list:
         target = data[regs['reg'][0]][regs['reg'][1]]
      else:
         target = data[regs['reg']]
      if not target:
         print("Data target is None in apply_asm_mask({}, {}) (line {})".format(regs, src, self.currentLine))
         return
      if len(regs['indexes']) > 1:
         for r in regs['indexes']:
            if regs['reg'].startswith("o"):
               if type(src[r]) is float:
                  target['xyzw'[r]].default_value = src[r]
               elif src[r] is None:
                  print("src[{}] is none in apply_asm_mask({}, {}) (line {})".format(r, regs, src, self.currentLine))
               else:
                  mtl.node_tree.links.new(target['xyzw'[r]], src[r])
            else:
               target['xyzw'[r]] = src[r]
      elif len(regs['indexes']) == 1:
         if regs['reg'].startswith("o"):
            if type(src[0]) is float:
               target['xyzw'[regs['indexes'][0]]].default_value = src[0]
            elif src[0] is None:
               print("src[0] is none in apply_asm_mask({}, {}) (line {})".format(regs, src, self.currentLine))
            else:
               mtl.node_tree.links.new(target['xyzw'[regs['indexes'][0]]], src[0])
         else:
            target['xyzw'[regs['indexes'][0]]] = src[0]
      else:
         if regs['reg'].startswith("o"):
            if type(src[0]) is float:
               target.default_value = src[0]
            elif src[0] is None:
               print("src[0] is none in apply_asm_mask({}, {}) (line {})".format(regs, src, self.currentLine))
            else:
               mtl.node_tree.links.new(target, src[0])
         else:
            print("Dest has no components in apply_asm_mask({}, {}) (line {})".format(regs, src, self.currentLine))
         
   
   def asm_dcl_indexableTemp_custom(words):
      xid, size, parts = self.dclxRegEx.search(words[1]).group(1,2,3)
      data['x'+xid] = []
      for i in range(int(size)):
         data['x'+xid].append({})
         for p in range(int(parts)):
            data['x'+xid][i]["xyzw"[p]] = None

   # regs: {'reg':"r1", 'indexes':[2,3]} <- represents r1.zw
   # terms: a list of lists of asm inputs, which are each a list of up to 4 elements, which are the pieces of that input. Might be floats, or tuples of (mod,source,sourceletter)
   
   def asm_ge(regs, terms, sat=False):
      outputs = []
      for t in terms[0]:
         outputs.append(None)
      for r in regs['indexes']:
         if len(regs['indexes']) == 1:
            s = 0
         else:
            s = r
         loc = get_shader_location(data['nodeCount'])
         node = create_asm_node("Math", [loc[0]+10*s, loc[1]], [terms[1][s], terms[0][s]], "LESS_THAN", sat)
         data['nodeCount'] += 1
         outputs[s] = node.outputs[0]
      apply_asm_mask(regs, outputs)
   
   def asm_and(regs, terms, sat=False):
      outputs = []
      for t in terms[0]:
         outputs.append(None)
      for r in regs['indexes']:
         if len(regs['indexes']) == 1:
            s = 0
         else:
            s = r
         try:
            if float_to_hex(terms[0][s]) == "0x3f800000" or float_to_hex(terms[1][s]) == "0x3f800000":
               loc = get_shader_location(data['nodeCount'])
               node = create_asm_node("Math", [loc[0]+10*s, loc[1]], [terms[0][s], 1], "MULTIPLY", True)
               data['nodeCount'] += 1
               outputs[s] = node.outputs[0]
            else:
               print("unsupported command 'and' only works with specific inputs (line {})".format(self.currentLine))
         except IndexError:
            print("IndexError in asm_and({}, {}, {}) (line {})".format(regs, terms, sat, self.currentLine))
      apply_asm_mask(regs, outputs)
   
   def asm_BASICOP(regs, terms, sat=False, op="ADD"):
      outputs = []
      for t in terms[0]:
         outputs.append(None)
      for r in regs['indexes']:
         if len(regs['indexes']) == 1:
            s = 0
         else:
            s = r
         loc = get_shader_location(data['nodeCount'])
         node = create_asm_node("Math", [loc[0]+10*s, loc[1]], [term[s] for term in terms], op, sat)
         data['nodeCount'] += 1
         outputs[s] = node.outputs[0]
      apply_asm_mask(regs, outputs)
   
   def asm_exp_sat(regs, terms):
      asm_exp(regs, terms, True)
      
   def asm_exp(regs, terms, sat=False):
      outputs = []
      for t in terms[0]:
         outputs.append(None)
      for r in regs['indexes']:
         if len(regs['indexes']) == 1:
            s = 0
         else:
            s = r
         loc = get_shader_location(data['nodeCount'])
         node = create_asm_node("Math", [loc[0]+10*s, loc[1]], [2, terms[0][s]], "POWER", sat)
         data['nodeCount'] += 1
         outputs[s] = node.outputs[0]
      apply_asm_mask(regs, outputs)

   def asm_log_sat(regs, terms):
      asm_log(regs, terms, True)
      
   def asm_log(regs, terms, sat=False):
      outputs = []
      for t in terms[0]:
         outputs.append(None)
      for r in regs['indexes']:
         if len(regs['indexes']) == 1:
            s = 0
         else:
            s = r
         loc = get_shader_location(data['nodeCount'])
         node = create_asm_node("Math", [loc[0]+10*s, loc[1]], [terms[0][s], 2], "LOGARITHM", sat)
         data['nodeCount'] += 1
         outputs[s] = node.outputs[0]
      apply_asm_mask(regs, outputs)

   def asm_dpX(regs, terms, sat=False, num=3):
      outputs = []
      nodes = []
      for c in range(num):
         nodes.append(create_asm_node("Math", get_shader_location(data['nodeCount']), [terms[0][c], terms[1][c]], "MULTIPLY", False))
         data['nodeCount'] += 1
      for a in range(num-1):
         nodes.append(create_asm_node("Math", [nodes[a].location[0]+150, nodes[a].location[1]], [
            nodes[a].outputs[0] if a == 0 else nodes[num-1+a].outputs[0],
            nodes[a+1].outputs[0]
         ], "ADD", False))
      nodes[len(nodes)-1].use_clamp = sat
      outputs.append(nodes[len(nodes)-1].outputs[0])
      apply_asm_mask(regs, outputs)

   def asm_dp2_sat(regs, terms):
      asm_dpX(regs, terms, True, 2)

   def asm_dp2(regs, terms):
      asm_dpX(regs, terms, False, 2)

   def asm_dp3_sat(regs, terms):
      asm_dpX(regs, terms, True, 3)

   def asm_dp3(regs, terms):
      asm_dpX(regs, terms, False, 3)

   def asm_dp4_sat(regs, terms):
      asm_dpX(regs, terms, True, 4)

   def asm_dp4(regs, terms):
      asm_dpX(regs, terms, False, 4)
      
   def asm_mov_sat(regs, terms):
      asm_mov(regs, terms, True)

   def asm_mov(regs, terms, sat=False):
      outputs = []
      for t in terms[0]:
         outputs.append(None)
      for r in regs['indexes']:
         if len(regs['indexes']) == 1:
            s = 0
         else:
            s = r
         loc = get_shader_location(data['nodeCount'])
         node = create_asm_node("Math", [loc[0]+10*s, loc[1]], [terms[0][s], 0], "ADD", sat)
         data['nodeCount'] += 1
         outputs[s] = node.outputs[0]
      apply_asm_mask(regs, outputs)
      
   def asm_movc_sat(regs, terms):
      asm_movc(regs, terms, True)

   def asm_movc(regs, terms, sat=False):
      outputs = []
      for t in terms[0]:
         outputs.append(None)
      temp = regs['indexes']
      if len(temp) == 0:
         temp = [0]
      for r in temp:
         if len(regs['indexes']) == 1:
            s = 0
         else:
            s = r
         loc = get_shader_location(data['nodeCount'])
         compnode = create_asm_node("Math", loc, [terms[0][s], 0, 0], "COMPARE", False)
         nonode = create_asm_node("Math", [loc[0]+150, loc[1]-20], [terms[2][s], compnode.outputs[0]], "MULTIPLY", False)
         negnode = create_asm_node("Math", [loc[0]+150, loc[1]+20], [1, compnode.outputs[0]], "SUBTRACT", False)
         yesnode = create_asm_node("Math", [loc[0]+300, loc[1]+20], [terms[1][s], negnode.outputs[0]], "MULTIPLY", False)
         finalnode = create_asm_node("Math", [loc[0]+300, loc[1]-20], [yesnode.outputs[0], nonode.outputs[0]], "ADD", sat)
         data['nodeCount'] += 1
         outputs[s] = finalnode.outputs[0]
      apply_asm_mask(regs, outputs)
      
   def asm_bfi_sat(regs, terms):
      asm_bfi(regs, terms, True)
      
   def asm_bfi(regs, terms, sat=False):
      if len(terms) != 4:
         print("Incorrect number of terms (requires 4): {}({}, {}, {}) (line {})".format("asm_bfi", regs, terms, sat, self.currentLine))
         return
      if len(terms[2]) > 1:
         print("Invalid third term, requires one component: {}({}, {}, {}) (line {})".format("asm_bfi", regs, terms, sat, self.currentLine))
         return
      outputs = []
      if terms[0][0] != 28 or terms[1][0] != 4:
         print("asm_bfi assumes 28 and 4 are first two terms, but {} and {} given instead. Using 28 and 4 anyway... (line {})".format(terms[0][0], terms[1][0], self.currentLine))
      node = create_asm_node("Math", get_shader_location(data['nodeCount']), [terms[2][0], 16, terms[3][0]], "MULTIPLY_ADD", sat)
      data['nodeCount'] += 1
      outputs.append(node.outputs[0])
      apply_asm_mask(regs, outputs)

   def asm_utof_sat(regs, terms):
      asm_mov(regs, terms, True)
      
   def asm_utof(regs, terms, sat=False):
      asm_mov(regs, terms, sat)

   def asm_ne_sat(regs, terms):
      asm_ne(regs, terms, True)
      
   def asm_ne(regs, terms, sat=False):
      outputs = []
      for t in terms[0]:
         outputs.append(None)
      for r in regs['indexes']:
         if len(regs['indexes']) == 1:
            s = 0
         else:
            s = r
         loc = get_shader_location(data['nodeCount'])
         node1 = create_asm_node("Math", [loc[0]+10*s, loc[1]], [terms[0][s], terms[1][s], 0], "COMPARE", False)
         node2 = create_asm_node("Math", [loc[0]+150+10*s, loc[1]], [1, node1.outputs[0]], "SUBTRACT", sat)
         data['nodeCount'] += 1
         outputs[s] = node2.outputs[0]
      apply_asm_mask(regs, outputs)

   def create_asm_node(nodetype, loc, inputs, op=None, sat=None):
      node = mtl.node_tree.nodes.new("ShaderNode"+nodetype)
      node.hide = True
      node.location = loc
      if op:
         node.operation = op
      if sat:
         node.use_clamp = sat
      for i in range(len(inputs)):
         if type(inputs[i]) is float or type(inputs[i]) is int:
            node.inputs[i].default_value = inputs[i]
         elif type(inputs[i]) is tuple:
            connect_node(node.inputs[i], inputs[i])
         elif isinstance(inputs[i], bpy.types.NodeSocket):
            mtl.node_tree.links.new(node.inputs[i], inputs[i])
         elif isinstance(inputs[i], bpy.types.ShaderNode):
            mtl.node_tree.links.new(node.inputs[i], inputs[i].outputs[0])
         else:
            print("unable to create link to new node in create_asm_node({}, {}, {}, {}, {}) (line {})".format(nodetype, loc, inputs, op, sat))
      return node

   def connect_node(input, term):
      if type(term) is tuple:
         if type(term[1]) is list:
            src = data[term[1][0]][term[1][1]][term[2]]['output']
         else:
            src = data[term[1]][term[2]]
         if src:
            if term[0] == "-":
               prenode = create_asm_node("Math", [0,0], [src, -1], "MULTIPLY", False)
               if input:
                  prenode.location = [input.node.location[0]-150, input.node.location[1]]
                  mtl.node_tree.links.new(input, prenode.outputs[0])
                  return src
               else:
                  prenode.location = get_shader_location(data['nodeCount'])
                  data['nodeCount'] += 1
                  return prenode.outputs[0]
            elif term[0] == "|":
               prenode = create_asm_node("Math", [0,0], [src], "ABSOLUTE", False)
               if input:
                  prenode.location = [input.node.location[0]-150, input.node.location[1]]
                  mtl.node_tree.links.new(input, prenode.outputs[0])
                  return src
               else:
                  prenode.location = get_shader_location(data['nodeCount'])
                  data['nodeCount'] += 1
                  return prenode.outputs[0]
            elif term[0] == "-|":
               prenode1 = create_asm_node("Math", [0,0], [src], "ABSOLUTE", False)
               prenode2 = create_asm_node("Math", [0,0], [src, -1], "MULTIPLY", False)
               if input:
                  prenode1.location = [input.node.location[0]-150, input.node.location[1]+20]
                  prenode2.location = [input.node.location[0]-150, input.node.location[1]-20]
                  mtl.node_tree.links.new(input, prenode2.outputs[0])
                  return src
               else:
                  loc = get_shader_location(data['nodeCount'])
                  prenode1.location = [loc[0]-150, loc[1]+20]
                  prenode2.location = [loc[0]-150, loc[1]-20]
                  data['nodeCount'] += 1
                  return prenode2.outputs[0]
            else:
               if input:
                  if type(src) is float:
                     input.default_value = src
                  else:
                     mtl.node_tree.links.new(input, src)
               return src
         else:
            print("tried to link to a nonexistent node (line {})".format(self.currentLine))
            return None
      elif type(term) is float:
         if input:
            input.default_value = term
         return term
      else:
         print("unknown problem with connect_node({}, {}) (line {})".format(input, term, self.currentLine))
         return None
   
   def __str__(self) -> str:
      result = []
      result.append("--- Begin str(RipShader) ---")
      result.append("  Shader File:   {}".format(self.fileName))
      result.append("  Directory:  {}".format(self.fileDir))
      result.append("  Shader Type: {}".format(["Vertex Shader","Pixel Shader"][self.shaderType]))
      if self.parsed:
         result.append("  Shader Version: {}".format(self.shaderVersion))
         result.append("  Global Flags: {}".format(self.globalFlags))
      result.append("---  End str(RipShader)  ---")
      return "\n".join(result)

class RipNode:
   """Corresponds to a node in a Blender material, but without any references to the Blender API
   """
   
   basicMaths = {
      'add': {'operation':"ADD"},
      'div': {'operation':"DIVIDE"},
      'frc': {'operation':"FRACT"},
      'lt': {'operation':"LESS_THAN"},
      'mad': {'operation':"MULTIPLY_ADD"},
      'max': {'operation':"MAXIMUM"},
      'min': {'operation':"MINIMUM"},
      'mul': {'operation':"MULTIPLY"},
      'round_ne': {'operation':"ROUND"},
      'round_ni': {'operation':"FLOOR"},
      'round_pi': {'operation':"CEIL"},
      'round_z': {'operation':"TRUNC"},
      'rsq': {'operation':"INVERSE_SQRT"},
      'sqrt': {'operation':"SQRT"},
   }
   
   def __init__(self, shader, type):
      self.shader = shader
      self.type = type
      self.createdLine = shader.currentLine
      self.inputs = {}
      self.outputs = {}
      self.options = {}
      self.shader.nodes.append(self)
   
   def input(self, id=0, connect=None):
      if id not in self.inputs:
         self.inputs[id] = RipNodeInput(self, id)
      if connect is not None:
         self.inputs[id].connect(connect)
      return self.inputs[id]
   
   def output(self, id=0, connect=None):
      if id not in self.outputs:
         self.outputs[id] = RipNodeOutput(self, id)
      if connect is not None:
         self.outputs[id].connect(connect)
      return self.outputs[id]
   
   def __repr__(self):
      return str(self)
   
   def __str__(self):
      return "<{} node created at line {}>".format(self.type, self.createdLine)

class RipNodeOutput:
   def __init__(self, node, id):
      self.node = node
      self.id = id
      self.connections = []
   
   def connect(self, input, oneWay=False):
      if isinstance(input, RipNodeInput):
         self.connections.append(input)
         if not oneWay:
            input.connect(self, True)
      else:
         raise TypeError("Tried to connect something other than a RipNodeInput ({}) to a RipNodeOutput (line {})".format(type(input), self.node.shader.currentLine))
      return self
   
   def __repr__(self):
      return str(self)
   
   def __str__(self):
      return "<RipNodeOutput {} of {}>".format(self.id, self.node)

class RipNodeInput:
   def __init__(self, node, id):
      self.node = node
      self.id = id
      self.connection = None
   
   def connect(self, output, oneWay=False):
      if isinstance(output, RipNodeOutput):
         if self.connection is not None:
            self.connection.connections.remove(self)
            print("Replacing connection of an input, is this intended? (line {})".format(self.node.shader.currentLine))
         self.connection = output
         if not oneWay:
            output.connect(self, True)
      else:
         raise TypeError("Tried to connect something other than a RipNodeOutput ({}) to a RipNodeInput (line {})".format(type(output), self.node.shader.currentLine))
      return self
   
   def __repr__(self):
      return str(self)
   
   def __str__(self):
      return "<RipNodeInput {} of {}>".format(self.id, self.node)