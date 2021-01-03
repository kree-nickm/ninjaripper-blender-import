import os
import time
import struct
from functools import reduce

# Needed for stand-alone tests
import importlib
if importlib.find_loader("bpy") is not None:
   from .RipShader import RipShader
else:
   from RipShader import RipShader

class RipFile:
   typeLookup = ["FLOAT", "UINT", "SINT"]
   typePackLookup = ["f", "L", "l"]
   
   def __init__(self, filePath: str):
      self.parsed = False
      if not os.path.isfile(filePath):
         raise ValueError("String '{}' passed to RipFile(str) is not a valid file path.".format(filePath))
      self.filePath = os.path.normpath(filePath)
      self.fileDir, self.fileName = os.path.split(self.filePath)
      self.fileLabel, self.fileExt = os.path.splitext(self.fileName)
      if self.fileExt.upper() != ".RIP":
         raise ValueError("File path '{}' passed to RipFile is not a RIP file. ({})".format(filePath, self.fileExt))
      self.shaderDir = os.path.join(os.path.dirname(self.fileDir), "Shaders")
      if not os.path.isdir(self.shaderDir):
         self.shaderDir = None
   
   def parse(self, xyzOrder="xzy", uvOrder="uW", scale=1.0, keep2D=False, keepUntextured=False):
      parseStart = time.process_time()
      with open(self.filePath, 'rb') as self.file:
         signature, version = self.__read('LL', 8)
         if signature != 3735929054:
            print("Invalid RIP signature. Continuing anyway, but this might not work...")
         if version != 4:
            print("Invalid RIP version. Expected {}, found {}. Continuing anyway, but this might not work...".format(4, version))
         
         self.faceCount, self.vertexCount, self.vertexSize, self.textureCount, self.shaderCount, self.semanticCount = self.__read('LLLLLL', 24)
         
         is3D = False
         self.semantics = []
         for i in range(self.semanticCount):
            semanticData = {'name': self.__readString()}
            semanticData['nameUpper'] = semanticData['name'].upper()
            semanticData['index'], semanticData['offset'], semanticData['size'], semanticData['typeCount'] = self.__read('LLLL', 16)
            semanticData['label'] = "{}{}".format(semanticData['name'], semanticData['index'])
            semanticData['types'] = []
            for k in range(semanticData['typeCount']):
               semanticData['types'].append(self.__read('L', 4)[0])
            self.semantics.append(semanticData)
            if semanticData['nameUpper'] == "POSITION" and semanticData['typeCount'] == 3:
               is3D = True
         
         if not is3D and not keep2D:
            print("{}: skipping because not 3D".format(self.fileLabel))
            return False
         
         self.textures = []
         for i in range(self.textureCount):
            texture = {'fileName': self.__readString()}
            texture['filePath'] = os.path.join(self.fileDir, texture['fileName'])
            self.textures.append(texture)
         
         if len(self.textures) == 0 and not keepUntextured:
            print("{}: skipping because untextured".format(self.fileLabel))
            return False
         
         self.shaders = []
         for i in range(self.shaderCount):
            self.shaders.append(RipShader(self.shaderDir, self.__readString(), self.textures))
         
         self.faces = []
         for i in range(self.faceCount):
            self.faces.append(self.__read('LLL', 12))
         
         self.pMax = []
         self.pMin = []
         self.vertexes = []
         for i in range(self.vertexCount):
            vertex = {'index': i}
            for semantic in self.semantics:
               format = ""
               for t in semantic['types']:
                  format += self.typePackLookup[t]
               data = self.__read(format, semantic['size'])
               if semantic['nameUpper'] == "POSITION":
                  if len(self.pMax) == 0:
                     for d in data:
                        self.pMax.append(d)
                  if len(self.pMin) == 0:
                     for d in data:
                        self.pMin.append(d)
                  for i in range(len(data)):
                     if data[i] > self.pMax[i]:
                        self.pMax[i] = data[i]
                     if data[i] < self.pMin[i]:
                        self.pMin[i] = data[i]
               # TODO: I would prefer if scaling and ordering was done in RipMesh, so that the parsed data is authentic to the saved file
               if semantic['nameUpper'] == "POSITION" or semantic['nameUpper'] == "NORMAL":
                  vertex[semantic['label']] = []
                  for i in xyzOrder:
                     if i == "x":
                        vertex[semantic['label']].append((data[0] if len(data) > 0 else 0) * scale)
                     elif i == "y":
                        vertex[semantic['label']].append((data[1] if len(data) > 1 else 0) * scale)
                     elif i == "z":
                        vertex[semantic['label']].append((data[2] if len(data) > 2 else 0) * scale)
                     elif i == "X":
                        vertex[semantic['label']].append((data[0] if len(data) > 0 else 0) * -1 * scale)
                     elif i == "Y":
                        vertex[semantic['label']].append((data[1] if len(data) > 1 else 0) * -1 * scale)
                     elif i == "Z":
                        vertex[semantic['label']].append((data[2] if len(data) > 2 else 0) * -1 * scale)
                     else:
                        raise ValueError("xyzOrder parameter ({}) has invalid character ({})".format(xyzOrder, i))
               elif semantic['nameUpper'] == "TEXCOORD":
                  vertex[semantic['label']] = []
                  for i in uvOrder:
                     if i == "u":
                        vertex[semantic['label']].append((data[0] if len(data) > 0 else 0))
                     elif i == "v":
                        vertex[semantic['label']].append((data[1] if len(data) > 1 else 0))
                     elif i == "U":
                        vertex[semantic['label']].append((data[0] if len(data) > 0 else 0) * -1)
                     elif i == "V":
                        vertex[semantic['label']].append((data[1] if len(data) > 1 else 0) * -1)
                     elif i == "o":
                        vertex[semantic['label']].append((data[0] if len(data) > 0 else 0) + 1)
                     elif i == "w":
                        vertex[semantic['label']].append((data[1] if len(data) > 1 else 0) + 1)
                     elif i == "O":
                        vertex[semantic['label']].append((data[0] if len(data) > 0 else 0) * -1 + 1)
                     elif i == "W":
                        vertex[semantic['label']].append((data[1] if len(data) > 1 else 0) * -1 + 1)
                     else:
                        raise ValueError("uvOrder parameter ({}) has invalid character ({})".format(uvOrder, i))
               else:
                  vertex[semantic['label']] = data
            self.vertexes.append(vertex)
         
         parseTime = time.process_time() - parseStart
         print("{}: parse took {}s".format(self.fileLabel, parseTime))
         self.parsed = True
      return True
   
   def __read(self, format, size):
      return struct.unpack(format, self.file.read(size))
   
   def __readString(self) -> str:
      result = ""
      done = False
      while not done:
         val = self.__read('B', 1)[0]
         if val == 0:
            done = True
         else:
            result += chr(val)
      return result
   
   def seemsEqual(self, other):
      if not isinstance(other, RipFile):
         return False
      if not self.parsed or not other.parsed:
         return False
      if len(self.faces) != len(other.faces):
         return False
      if len(self.vertexes) != len(other.vertexes):
         return False
      if len(self.pMax) != len(other.pMax):
         return False
      else:
         for i in range(len(self.pMax)):
            if self.pMax[i] != other.pMax[i]:
               return False
      if len(self.pMin) != len(other.pMin):
         return False
      else:
         for i in range(len(self.pMin)):
            if self.pMin[i] != other.pMin[i]:
               return False
      return True
   
   def __str__(self) -> str:
      result = []
      result.append("--- Begin str(RipFile) ---")
      result.append("  RIP File:   {}".format(self.fileLabel))
      result.append("  Directory:  {}".format(self.fileDir))
      result.append("  Shader Dir: {}".format(self.shaderDir))
      if self.parsed:
         result.append("  Faces: {}".format(self.faceCount))
         result.append("  Vertexes: {}".format(self.vertexCount))
         result.append("  Vertex Size: {}".format(self.vertexSize))
         result.append("  Textures: {} ({})".format(self.textureCount, reduce(lambda a,b: b['fileName'] if a == "" else a+", "+b['fileName'], self.textures, "")))
         result.append("  Shaders: {} ({})".format(self.shaderCount, reduce(lambda a,b: b.fileName if a == "" else a+", "+b.fileName, self.shaders, "")))
         result.append("  Semantics: {}".format(self.semanticCount))
         for semantic in self.semantics:
            semantic['typeList'] = ""
            for t in semantic['types']:
               if semantic['typeList'] == "":
                  semantic['typeList'] += self.typeLookup[t]
               else:
                  semantic['typeList'] += " " + self.typeLookup[t]
            result.append("    {name}: idx={index} offset={offset} size={size} types={typeCount} ({typeList})".format(**semantic))
      result.append("---  End str(RipFile)  ---")
      return "\n".join(result)
   
   def outputData(self):
      if self.parsed:
         with open("vertexLog.tsv", 'w') as log:
            for semantic in self.semantics:
               for i in range(semantic['typeCount']):
                  log.write("{}[{}]\t".format(semantic['label'], i))
            log.write("\n")
            for vertex in self.vertexes:
               for semantic in self.semantics:
                  for i in range(semantic['typeCount']):
                     log.write(str(vertex[semantic['label']][i]) + "\t")
               log.write("\n")
      else:
         print("You must parse() before outputData()")
      

# Testing, IGNORE ME
if __name__ == "__main__":
   #filePath = "D:\\Libraries\\Downloads\\Blender\\NinjaRipped\\_NinjaRipper\\2020.12.03_18.01.12_bg3_dx11.exe_Shadowheart\\2020.12.03_18.37.48_bg3_dx11.exe\\Mesh_0402.rip" # shadowheart hair
   #filePath = "D:\\Libraries\\Downloads\\Blender\\NinjaRipped\\_NinjaRipper\\2020.11.27_02.19.38_DarkSoulsIII.exe_FirekeeperEnding\\2020.11.27_02.25.04_DarkSoulsIII.exe\\Mesh_0307.rip" #ds3
   filePath = "D:\\Libraries\\Downloads\\Blender\\NinjaRipped\\_NinjaRipper\\2020.12.07_09.57.28_bg3_dx11.exe_Laezel2\\Rips\\Mesh_0157.rip" #laezel ears
   rip = RipFile(filePath)
   rip.parse()
   from pprint import pprint
   for shader in rip.shaders:
      if shader.shaderType == 1:
         shader.parse()
         shader.registers['o1']['x'].node.traverse()