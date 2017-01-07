# -*- coding: utf-8 -*-
"""
Created on Thu Nov 19 16:45:00 2015

Figura takes all of the parameters and the input outline and creates each layer
for every part. These layers are then converted to Gcode in the form of a list
of strings. The list is stored in self.gcode which can then be accessed and written
to the correct output file by using join().

A layer in Figura starts as a list of LineGroups, typically shells in (Outlines)
and then an Infill but could also be a variety of different outlines all printed
at the same Z-height. The list of layers is then organized and turned into a single
LineGroup with the order of the lines being the print order of the layer. The
goal is to allow easy adjustability when deciding how to organize a layer.
Different organizedLayer() methods could be written calling different
organizing coroutines in the LineGroups to create an ideal print order.


@author: lvanhulle
"""

from point import Point
from infill import Infill
from linegroup import LineGroup
import constants as c
from outline import Outline, Section
import trimesh
from functools import lru_cache
import os

class Figura:  
    
    def __init__(self, param, g_code):
        
        self.data_points =  []
        
        self.gc = g_code
        self.pr = param
        
        self.partCount = 1 # The current part number


    def masterGcode_gen(self):
        yield self.gc.startGcode(bed_temp = self.pr.bed_temp, extruder_temp = self.pr.extruder_temp)
        for partParams in self.pr.everyPartsParameters:
            """ pr.everyPartsParameters is a generator of the parameters for the parts.
            The generator stops yielding additional parameters when there are no
            more parts left to print. The parameters are sent to layer_gen() which
            yields each layer of the part. The generator is sent to setGcode()
            along with the partParameters (for printing in the gcode).
            """
            print('\nPart number: ' + str(self.partCount))            
            print(partParams)
           
            yield '\n\n' + self.gc.comment('Part number: ' + str(self.partCount) + '\n')
            yield self.gc.comment(str(partParams) + '\n')
            
            yield from self.partGcode_gen(partParams)
                
            self.partCount += 1
        yield self.gc.endGcode()

    def layer_gen(self, partParams):
        """
        Creates and yields each organized layer for the part.
        
        Parameters
        ----------
        partParams - a tuple of the parameters for the part
        
        Yields
        ------
        tuple - (LineGroup of the layer ordered for printing, the namedtuple of
        the layer parameters so they can be printed in the gcode.)
        """  
        
        currHeight = 0
        layerCountdown = partParams.numLayers
        isFirstLayer = True
        sec_gen = self.pr.secgen()
        next(sec_gen)
        for layerParam in self.pr.layerParameters():
            if not layerCountdown:
                break
            currHeight += layerParam.layerHeight
            outlines_angles = sec_gen.send(currHeight)
            fullLayer = self.make_layer(outlines_angles, layerParam, isFirstLayer)
            yield (fullLayer.translate(partParams.shiftX, partParams.shiftY,
                                currHeight+self.pr.firstLayerShiftZ), layerParam)
            layerCountdown -= 1
            isFirstLayer = False
        print(self.make_layer.cache_info())
            
    @lru_cache(maxsize=16)
    def make_layer(self, outlines_angles, layerParam, isFirstLayer):
#        fullLayer = LineGroup()
        filledList = []
        for outline, angle in outlines_angles:
#            filledList = []
            if self.pr.nozzleOffset:
                outline = outline.offset(self.pr.nozzleOffset, c.INSIDE)
            if angle is None:
                angle = layerParam.infillAngle
            
            if isFirstLayer and self.pr.brims:
                filledList.extend(outline.shell_gen(number=self.pr.brims,
                                                    dist = self.pr.nozzleDiameter,
                                                    side = c.OUTSIDE,
                                                    ))

            filledList.extend(outline.shell_gen(number = layerParam.numShells,
                                                dist = self.pr.nozzleDiameter,
                                                side = c.INSIDE,
                                                ))
                    
            """
            To help with problems that occur when an offset outline has its sides
            collide or if the infill lines are co-linear with the trim lines we
            want to fudge the trimOutline outward just a little so that we end
            up with the correct lines.
            """
            trimOutline = outline.offset(layerParam.trimAdjust
                                         - self.pr.nozzleDiameter * layerParam.numShells,
                                         c.OUTSIDE)
                            
            if trimOutline and self.pr.pattern: # If there is an outline to fill and we want an infill
                infill = Infill(trimOutline,
                                    layerParam.pathWidth, angle, #layerParam.infillAngle,
                                    shiftX=layerParam.infillShiftX, shiftY=layerParam.infillShiftY,
                                    design=self.pr.pattern, designType=self.pr.designType)
                filledList.append(infill)
#            organizedLayer = self.organizedLayer(filledList)
#            if not organizedLayer:
#                raise(Exception('Parameter setting produced no tool path. \n' +
#                                'Ensure numLayers is >0 and there is at least one ' +
#                                'shell if no infill is used.'))
#            fullLayer += organizedLayer

        return self.organizedLayer(filledList)
    
    def partGcode_gen(self, partParams):        
        layerNumber = 1
        yield self.gc.newPart()
        totalExtrusion = 0
        
        for layer, layerParam in self.layer_gen(partParams):
            extrusionRate = (partParams.solidityRatio*layerParam.layerHeight*
                            self.pr.nozzleDiameter/self.pr.filamentArea)
            yield self.gc.comment('Layer: ' + str(layerNumber) + '\n')
            yield self.gc.comment(str(layerParam) + '\n')
            yield self.gc.comment('T' + str(self.partCount) + str(layerNumber) + '\n')
            yield self.gc.comment('M6\n')
            yield self.gc.operatorMessage('Layer', layerNumber, 'of', partParams.numLayers)
            yield self.gc.rapidMove(layer[0].start, atClearance = True)
            yield self.gc.firstApproach(totalExtrusion, layer[0].start)
            
            prevLoc = layer[0].start
            self.data_points.append(['start'])
            for line in layer:
                if prevLoc != line.start:
                    if (prevLoc - line.start) < self.pr.MAX_FEED_TRAVERSE:
                        yield self.gc.rapidMove(line.start)
                    else:
                        yield self.gc.retractLayer(totalExtrusion, prevLoc)
                        yield self.gc.rapidMove(line.start, atClearance=True)
                        yield self.gc.approachLayer(totalExtrusion, line.start)
                        
                line.extrusionRate = extrusionRate
                totalExtrusion += line.length*line.extrusionRate
                yield self.gc.feedMove(line.end, totalExtrusion,
                                          partParams.printSpeed)
                prevLoc = line.end
            
                self.data_points.append([(','.join(str(i) for i in line.start.normalVector[:3])+',')+
                                        (','.join(str(i) for i in line.end.normalVector[:3])),
                                        ('layer_number:' + str(layerNumber) + ':  part_number:' + str(self.partCount) + ':')])
            self.data_points.append(['end'])
            yield self.gc.retractLayer(totalExtrusion, layer[-1].end)
            yield '\n'
            layerNumber += 1
        yield self.gc.comment('Extrusion amount for part is ({:.1f} mm)\n\n'.format(totalExtrusion))

            
    def organizedLayer(self, inOutlines):
        """ Takes in a list of LineGroup objects and returns them as an organized layer.
        
        A dictonary was used to hold the coroutines from linegroup since we
        will want to delete keys, value pairs while iterating throught the dict.
        
        The coroutines yield in a boolean and a Point and then yield back out
        the line which is 'closest' to the point. 'Closest' being in quotes
        because we could use any number of parameters to decide which line is
        closest from Euclidean distance of end points to time since its neighbor
        was printed (for cooling purposes). The yielded in boolean is whether or
        not the previous line was used.
        
        Currently if the LineGroup with the closest line is a outline then the
        entire outline is printed before checking any other LineGroups again.
        
        Parameters
        ----------
        inOutlines - a list of LineGroups that make up the layer
        
        Return
        ------
        A single organized LineGroup 
        """
        layer = LineGroup()
        
        lineCoros = {i : inOutlines[i].nearestLine_Coro(i) for i in range(len(inOutlines))}
        
        for coro in lineCoros.values():
            next(coro)

        """
        Find the lower left most point of the boudnding box which encloses
        the layer and use that as the starting point for the sort.
        """
        minX = min(i.minX for i in inOutlines)
        minY = min(i.minY for i in inOutlines)
        lastPoint = Point(minX, minY) # The starting point for the sort
        indexOfClosest = -1 # A default value for the inital run
        while True:
            results = []
            for key in list(lineCoros.keys()):
                try:
                    results.append(lineCoros[key].send(
                        (c.USED if key == indexOfClosest else c.NOT_USED, lastPoint)))
                except StopIteration:
                    """ If we get a StopIteration exception from the coroutine
                    that means the LineGroup has no more Lines and we can remove
                    it from the dictionary. """                    
                    del lineCoros[key]
                    
            if len(results) == 0: break # No more items in the dictionary
            result = min(results, key=lambda x:x.distance)
            line = result.line
            indexOfClosest = result.name
            lastPoint = line.end
            layer.append(line)
            if isinstance(inOutlines[indexOfClosest], Outline):
                """ If the closest line was from a Outline then go around the whole
                outline without checking any other LineGroup. Outlines are required
                to be continuous contours (except if the have internal holes) so
                there is no need to check any other LineGroup for a closer line.
                Plus if the outline was being used as a brim to help start a print
                we would not want to stop partially way through the brim.
                """
                while True:
                    try:
                        line = lineCoros[indexOfClosest].send((c.USED, lastPoint))[0]
                    except StopIteration:
                        del lineCoros[indexOfClosest]
                        break
                    else:
                        """ A reminder than an else is run if there is no exception. """
                        lastPoint = line.end
                        layer.append(line)
        return layer
    
#    def __str__(self):
#        tempString = ''
#        layerNumber = 1
#        for layer in self.layers:
#            tempString += self.pr.comment + 'T' + str(layerNumber) + '\n'
#            tempString += self.pr.comment + 'M6\n'
#            tempString += str(layer)
#            layerNumber += 1
#        return tempString