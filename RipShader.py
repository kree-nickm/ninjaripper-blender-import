import os
import re
import struct
import time
from math import floor
from functools import reduce

def float_to_hex(f):
   if type(f) is float:
      return hex(struct.unpack('<I', struct.pack('<f', f))[0])
   else:
      return None

class RipShader:
   cbRegEx = re.compile("//\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+);\s*//\s+Offset:\s+(\d+)\s+Size:\s+(\d+)")
   rRegEx = re.compile("//\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s+(\d+)\s+(\d+)")
   ioRegEx = re.compile("//\s+([a-zA-Z0-9_]+)\s+(\d+)\s+([xyzw]+)\s+(\d+)\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s+([xyzw]+)")
   
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
      loadStart = time.process_time()
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
      loadTime = time.process_time() - loadStart
      print("{}: Shader parse took {}s".format(self.fileName, loadTime))
   
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
         pass
         # Deal with these during sample_indexable
         
      elif words[0] == "dcl_input" or words[0] == "dcl_input_ps":
         if words[0] == "dcl_input":
            parts = words[1].split(".")
         else:
            parts = words[2].split(".")
         if len(parts) > 1:
            for c in parts[1]:
               node = RipNode(self, "Value")
               node.options['name'] = self.data['input'][parts[0]][c]['name']
               node.options['label'] = self.data['input'][parts[0]][c]['name']
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
            
      elif words[0] == "dcl_indexableTemp":
         parts = words[1].split("[")
         if len(parts) > 1 and len(words) == 3:
            parts[1] = parts[1][:-1]
            self.registers[parts[0]] = []
            for i in range(int(parts[1])):
               self.registers[parts[0]].append({})
               for c in range(int(words[2])):
                  self.registers[parts[0]][i]["xyzw"[c]] = None
         else:
            print("Invalid indexableTemp declaration {} (line {})".format(words, self.currentLine))
      
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
            
         if words[0][0] == "sample_indexable":
            texnode = RipNode(self, "TexImage")
            sepnode = RipNode(self, "SeparateRGB")
            texnode.options['imageData'] = self.data['resources'][words[3][0][1]]['data']
            texnode.options['name'] = self.data['resources'][words[3][0][1]]['name']
            texnode.options['label'] = self.data['resources'][words[3][0][1]]['name']
            texnode.output(0, sepnode.input())
            if words[3][0][1] not in self.registers:
               self.registers[words[3][0][1]] = {}
            self.registers[words[3][0][1]]['x'] = sepnode.output(0)
            self.registers[words[3][0][1]]['y'] = sepnode.output(1)
            self.registers[words[3][0][1]]['z'] = sepnode.output(2)
            self.registers[words[3][0][1]]['w'] = texnode.output(1)
            uvnode = RipNode(self, "CombineXYZ")
            uvnode.input(0, self.getOutputFromSrcTerm(words[2][0]))
            uvnode.input(1, self.getOutputFromSrcTerm(words[2][1]))
            texnode = self.registers[words[3][0][1]]['w'].node
            texnode.input(0, uvnode.output())
            texnode.options['sampler'] = self.data['resources'][words[4][0][1]]
            self.setRegister(words[1], [self.getRegisterFromTuple(word) for word in words[3]])
            
         elif words[0][0] in RipNode.basicMaths:
            # prepare for an output for each possible input component
            outputs = [None] * reduce(lambda a,b: max(len(b), a), words[2:], 0)
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               node = RipNode(self, "Math")
               node.options = RipNode.basicMaths[words[0][0]]
               node.options['use_clamp'] = (words[0][1] & 1 == 1)
               for i in range(2,len(words)):
                  if len(words[i]) != len(outputs):
                     print("DEBUG: term length mismatch, double-check that selecting the first one is ok (line {})".format(self.currentLine))
                  node.input(i-2, self.getOutputFromSrcTerm(words[i][cReal]))
               outputs[cReal] = node.output()
            self.setRegister(words[1], outputs)
            
         elif words[0][0] == "exp":
            # prepare for an output for each possible input component
            outputs = [None] * len(words[2])
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               node = RipNode(self, "Math")
               node.options['operation'] = "POWER"
               node.options['use_clamp'] = (words[0][1] & 1 == 1)
               node.input(0, 2.0)
               node.input(1, self.getOutputFromSrcTerm(words[2][cReal]))
               outputs[cReal] = node.output()
            self.setRegister(words[1], outputs)
            
         elif words[0][0] == "log":
            # prepare for an output for each possible input component
            outputs = [None] * len(words[2])
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               node = RipNode(self, "Math")
               node.options['operation'] = "LOGARITHM"
               node.options['use_clamp'] = (words[0][1] & 1 == 1)
               node.input(0, self.getOutputFromSrcTerm(words[2][cReal]))
               node.input(1, 2.0)
               outputs[cReal] = node.output()
            self.setRegister(words[1], outputs)
            
         elif words[0][0] == "ge":
            # prepare for an output for each possible input component
            outputs = [None] * max(len(words[2]), len(words[3]))
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               node = RipNode(self, "Math")
               node.options['operation'] = "LESS_THAN"
               node.options['use_clamp'] = (words[0][1] & 1 == 1)
               node.input(0, self.getOutputFromSrcTerm(words[3][cReal]))
               node.input(1, self.getOutputFromSrcTerm(words[2][cReal]))
               outputs[cReal] = node.output()
            self.setRegister(words[1], outputs)
            
         elif words[0][0] == "and":
            # prepare for an output for each possible input component
            outputs = [None] * max(len(words[2]), len(words[3]))
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               if float_to_hex(words[3][cReal]) == "0x3f800000":
                  node = RipNode(self, "Math")
                  node.options['operation'] = "ADD"
                  node.options['use_clamp'] = (words[0][1] & 1 == 1)
                  node.input(0, self.getOutputFromSrcTerm(words[2][cReal]))
                  node.input(1, 0.0)
                  outputs[cReal] = node.output()
               else:
                  print("unsupported command 'and' only works with specific inputs (line {})".format(self.currentLine))
            self.setRegister(words[1], outputs)
            
         elif words[0][0] == "dp2" or words[0][0] == "dp3" or words[0][0] == "dp4":
            dimensions = int(words[0][0][2])
            nodes = []
            for i in range(dimensions):
               node = RipNode(self, "Math")
               node.options['operation'] = "MULTIPLY"
               node.input(0, self.getOutputFromSrcTerm(words[2][i]))
               node.input(1, self.getOutputFromSrcTerm(words[3][i]))
               nodes.append(node)
            for a in range(dimensions-1):
               node = RipNode(self, "Math")
               node.options['operation'] = "ADD"
               node.input(0, nodes[a].output() if a == 0 else nodes[dimensions-1+a].output())
               node.input(1, nodes[a+1].output())
               nodes.append(node)
            nodes[len(nodes)-1].options['use_clamp'] = (words[0][1] & 1 == 1)
            self.setRegister(words[1], [nodes[len(nodes)-1].output()])
            
         elif words[0][0] == "mov" or words[0][0] == "utof":
            # prepare for an output for each possible input component
            outputs = [None] * len(words[2])
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               node = RipNode(self, "Math")
               node.options['operation'] = "ADD"
               node.options['use_clamp'] = (words[0][1] & 1 == 1)
               node.input(0, self.getOutputFromSrcTerm(words[2][cReal]))
               node.input(1, 0.0)
               outputs[cReal] = node.output()
            self.setRegister(words[1], outputs)
            
         elif words[0][0] == "movc":
            # prepare for an output for each possible input component
            outputs = [None] * max(len(words[2]), len(words[3]), len(words[4]))
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               compnode = RipNode(self, "Math")
               compnode.options['operation'] = "COMPARE"
               compnode.input(0, self.getOutputFromSrcTerm(words[2][cReal]))
               compnode.input(1, 0.0)
               compnode.input(2, 0.0)
               nonode = RipNode(self, "Math")
               nonode.options['operation'] = "MULTIPLY"
               nonode.input(0, self.getOutputFromSrcTerm(words[4][cReal]))
               nonode.input(1, compnode.output())
               negnode = RipNode(self, "Math")
               negnode.options['operation'] = "SUBTRACT"
               negnode.input(0, 1.0)
               negnode.input(1, compnode.output())
               yesnode = RipNode(self, "Math")
               yesnode.options['operation'] = "MULTIPLY"
               yesnode.input(0, self.getOutputFromSrcTerm(words[3][cReal]))
               yesnode.input(1, negnode.output())
               finalnode = RipNode(self, "Math")
               finalnode.options['operation'] = "ADD"
               finalnode.options['use_clamp'] = (words[0][1] & 1 == 1)
               finalnode.input(0, yesnode.output())
               finalnode.input(1, nonode.output())
               outputs[cReal] = finalnode.output()
            self.setRegister(words[1], outputs)
            
         elif words[0][0] == "bfi":
            # prepare for an output for each possible input component
            outputs = [None] * max(len(words[2]), len(words[3]), len(words[4]), len(words[5]))
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               if words[2][cReal] != 28:
                  print("bfi assumes 28 is first term, but {} given instead. Using 28 anyway... (line {})".format(words[2][cReal], self.currentLine))
               if type(words[3][cReal]) is not float:
                  print("bfi currently only supports constants as second term, {} given, result will be incorrect (line {})".format(words[3][cReal], self.currentLine))
                  words[3][cReal] = 0
               node = RipNode(self, "Math")
               node.options['operation'] = "MULTIPLY_ADD"
               node.options['use_clamp'] = (words[0][1] & 1 == 1)
               node.input(0, self.getOutputFromSrcTerm(words[4][cReal]))
               node.input(1, 2**words[3][cReal])
               node.input(2, self.getOutputFromSrcTerm(words[5][cReal]))
               outputs[cReal] = node.output()
            self.setRegister(words[1], outputs)
            
         elif words[0][0] == "ne":
            # prepare for an output for each possible input component
            outputs = [None] * max(len(words[2]), len(words[3]))
            components = words[1][1] if words[1][1] is not None and len(words[1][1]) > 0 else []
            for cMask in components:
               # if there's only one output, we don't mask the inputs, we just pick the first one
               cReal = 0 if len(components) == 1 else cMask
               node1 = RipNode(self, "Math")
               node1.options['operation'] = "COMPARE"
               node1.input(0, self.getOutputFromSrcTerm(words[2][cReal]))
               node1.input(1, self.getOutputFromSrcTerm(words[3][cReal]))
               node1.input(1, 0.0)
               node2 = RipNode(self, "Math")
               node2.options['operation'] = "SUBTRACT"
               node2.input(0, 1.0)
               node2.input(1, node1.output())
               outputs[cReal] = node2.output()
            self.setRegister(words[1], outputs)
            
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
         # Masks should always be in order, so we only need to check if a component exists.
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
      if len(srcParts) > 1:
         srcParts[1] = srcParts[1][:-1]
      if len(termParts) > 1:
         result = []
         for n in termParts[1]:
            if len(srcParts) > 1:
               result.append((mod, srcParts, n))
            else:
               result.append((mod, termParts[0], n))
         return result
      elif len(srcParts) > 1:
         return [(mod, srcParts, None)]
      else:
         return [(mod, termParts[0], None)]
   
   def getRegisterFromTuple(self, term):
      """Gets the register referred to by the given tuple parsed by parseASMSwizzle
      
      Parameters
      ----------
      term : tuple
         a 3-element tuple from parseASMSwizzle
      
      Returns
      -------
      RipNodeOutput
         the element of self.registers
      """
      
      if(type(term) is tuple and len(term) == 3):
         if type(term[1]) is list:
            return self.registers[term[1][0]][term[1][1]][term[2]]
         else:
            return self.registers[term[1]][term[2]]
      else:
         raise TypeError("Argument of getRegisterFromTuple must be a 3-element tuple, {} given (line {})".format(term, self.currentLine))
   
   def getOutputFromSrcTerm(self, term):
      if type(term) is tuple:
         reg = self.getRegisterFromTuple(term)
         if term[0] & 1 == 1:
            negnode = RipNode(self, "Math")
            negnode.options['operation'] = "MULTIPLY"
            negnode.input(0, reg)
            reg = negnode.output()
         if term[0] & 2 == 2:
            absnode = RipNode(self, "Math")
            absnode.options['operation'] = "ABSOLUTE"
            absnode.input(0, reg)
            reg = absnode.output()
         return reg
      elif type(term) is float:
         return term
      else:
         print("Invalid term '{}' (line {})".format(term, self.currentLine))
         return None
   
   def setRegister(self, dest, nodeOutputs):
      if dest[1] is None:
         if type(dest[0]) is list:
            self.registers[dest[0][0]][dest[0][1]] = nodeOutputs[0]
         else:
            self.registers[dest[0]] = nodeOutputs[0]
      else:
         if type(dest[0]) is list:
            target = self.registers[dest[0][0]][dest[0][1]]
         else:
            target = self.registers[dest[0]]
         if len(dest[1]) > 1:
            for r in dest[1]:
               target['xyzw'[r]] = nodeOutputs[r]
         elif len(dest[1]) == 1:
            target['xyzw'[dest[1][0]]] = nodeOutputs[0]
         else:
            raise ValueError("Destination components somehow empty (line {})".format(self.currentLine))
   
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
      self.blenderNode = None
      self.handled = False
   
   def traverse(self, prev=None):
      if not self.handled:
         for id in self.inputs:
            print("Handling input #{} of {}".format(id, self))
            if self.inputs[id].connection is not None:
               if self.inputs[id].handled:
                  print("ERROR: Infinite recursion detected!")
               else:
                  self.inputs[id].handled = True
                  self.inputs[id].connection.node.traverse(self)
            else:
               print("Value: ".format(self.inputs[id].defaultValue))
         self.handled = True
   
   def input(self, id=0, connect=None):
      if id not in self.inputs:
         self.inputs[id] = RipNodeInput(self, id)
      if type(connect) is float or type(connect) is int:
         self.inputs[id].defaultValue = float(connect)
      elif connect is not None:
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
      return "<{} node ({}) created at line {}>".format(self.type, self.options['operation'] if 'operation' in self.options else "", self.createdLine)

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
      self.defaultValue = 0.5
      self.handled = False # for use by RipMesh
   
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
