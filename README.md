# NinjaRipper Blender Import

*I have only tested this with Blender 2.8, so it might not work in 2.9. However, I did get a RIP file to import in my single test case, so it *might* work.*

A more advanced Blender add-on to import NinjaRipper RIP files into Blender. More options than previous iterations, including the ability to parse shader files. Based on the add-on by [Dummiesman](https://github.com/Dummiesman/RipImport) and later [xpawelsky](https://github.com/xpawelsky/RipImport), but rewritten to the point that I don't think further credit is needed.

## Import Options
* **Vertex Order:** How to translate the RIP file vertex coordinates X,Y,Z into Blender X,Y,Z. The default (-X, Z, Y) should be the only one you need, but other options exist for experiment's sake.
* **UV Order:** How to translate the RIP file UV coordinates X,Y into Blender X,Y. The default (U, -V+1) should be the only one you need, but other options exist for experiment's sake.
* **Scale:** Multiplier for the size of the imported mesh(es).
* **Re-use materials:** If multiple meshes are determined to use the same textures, they are assumed to also use the same material. In which case, the existing material will be re-used, rather than making a new one.
* **Import entire folder:** Import all RIP files that are in the same folder as the file you selected. Might take a long time, but can be quickened by some of the options below. *DO NOT* use this with 'import shaders' or you will be waiting a *LONG* time.
* **Import shaders:** Attempt to parse the VS and PS shader files in the Shaders directory, assuming you ripped them with NinjaRipper. This will add many nodes to each selected mesh's material in attempt to build a Blender material out of a DirectX HLSL assembly language shader. This is *NOT* a fully automated process; you *WILL* have to manually tweak the material nodes once it is done (see below). *DO NOT* use this with 'import entire folder' or you will be waiting a *LONG* time.
* **Keep 2D meshes:** Some ripped meshes will be 2-dimensional, which are usually ripped UI elements and the like. They are discarded by default to save time when using 'import entire folder', but check this box if you want to keep them.
* **Keep untextured meshes:** Some meshes have no textures, and I don't know what their purpose is. They are discarded by default to save time when using 'import entire folder', but check this box if you want to keep them.
* **Remove duplicate meshes:** Many meshes in a single ripped scene are duplicates of one another, but with different textures. Usually only one of them has usable textures. Check this box if you want the script to try to figure out which is the one usable mesh and discard the rest, in order to save time when using 'import entire folder'. It is unchecked by default, because this determination is not fool-proof, and might result in deleting the good mesh in the rare case where a bad mesh has the most textures.

## Importing Shaders
**Note: I am still working on rewriting this code at the time of this commit. Importing shaders will not currently work.**

Many people will tell you that the shaders output by NinjaRipper are worthless to Blender, because the shaders are written specifically for DirectX in HLSL, and Blender does not use DirectX. Those people are wrong. The shaders aren't usable in their existing assembly language form, but they can be parsed into something that Blender *can* use.

This script will parse through the assembly language HLSL files line-by-line, and add a shader node to the appropriate material that corresponds to the ASM instruction on each line, and will link the shader nodes together to perform all of the instructions that the HLSL shader describes.

The result will be a huge mess of a material file with nodes and lines all over the place, however, all of the math to convert the texture data into material data will be there. Normal maps, base color, sub-surface data, metallic, roughness, specular, etc. will all be somewhere in there if they were a part of the ripped scene. But, you might have to do some looking to find them, and potentially add some extra nodes yourself once you do.

**Note that for probably most games, this is way more trouble than it's worth.** Most games give you the normal map and base color textures files, along with other texture files containing reflectance data, and it's pretty self-explanatory how to plug it all into a Principled BDSF node and be done with it. But every so often, you may encounter a game with no base color texture, a normal map that makes no sense, multiple textures that mix together in dynamic ways, or some other thing that you really can't figure out without diving into the math between the textures and the game scene. This script will find all of that math for you. All you need to do is find which node outputs you need to plug into your Principled BDSF node, and probably tweak some of the Value/RGBColor input nodes, and then your imported mesh will appear exactly as it does in the game (lighting not withstanding).

Ideally, in the future I will make a tutorial that demonstrates this process. That said, every game that requires this might require a different process, but hopefully you can figure it out.
