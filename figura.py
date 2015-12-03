# -*- coding: utf-8 -*-
"""
Created on Thu Nov 19 16:45:00 2015

@author: lvanhulle
"""

import gcode as gc
import parameters as pr
import Point as p
import InFill as Inf

#Test for this comment here

class Figura:
    
    def __init__(self, inShape):
        layer = Inf.InFill(inShape)
        self.layers = [layer.translate(0, 0, pr.layerHeight*(currentLayer+1)) for currentLayer in range(pr.numLayers)]
        self.gcode = ''
        self.setGcode()
    
    def setGcode(self):
        self.gcode += gc.startGcode()
        layerNumber = 1
        for layer in self.layers:
            lines = self.organizeLines(layer.getLines())
            self.gcode += '\n\n;Layer: ' + str(layerNumber) + '\n'
            self.gcode += ';T' + str(layerNumber) + '\n'
            self.gcode += ';M6\n'
            self.gcode += gc.rapidMove(lines[0].start, pr.INCLUDE_Z)
            self.gcode += gc.firstApproach(lines[0].start)
            
            totalExtrusion = 0
            for line in lines:
                totalExtrusion += line.length*pr.extrusionRate
                self.gcode += gc.rapidMove(line.start, pr.OMIT_Z)
                self.gcode += gc.feedMove(line.end, pr.OMIT_Z, totalExtrusion)
            
            self.gcode += gc.retractLayer(totalExtrusion, lines[-1].end)
            layerNumber += 1
        self.gcode += gc.endGcode()
                
                
#TODO: change method to actually work for more than just 90 degree orientation            
    def organizeLines(self, lines):
        organizedLines = [lines.pop(0)]
        
        while len(lines) > 0:
            nearestEnd = lines[0].start
            nearestOffset = 0
            dist = nearestEnd.distance(organizedLines[0].end)
            isStart = True
            
            for i in range(len(lines)):
                tempDist = organizedLines[-1].end.distance(lines[i].start)
                if(tempDist < dist):
                    nearestEnd = lines[i].start
                    dist = tempDist
                    isStart = True
                    nearestOffset = i
                tempDist = organizedLines[-1].end.distance(lines[i].end)
                if(tempDist < dist):
                    nearestEnd = lines[i].end
                    dist = tempDist
                    isStart = False
                    nearestOffset = i
                if(dist == 0): break
            if(not isStart):
                lines[nearestOffset].flip()
            organizedLines.append(lines.pop(nearestOffset))
            
        return organizedLines
    
    def __str__(self):
        tempString = ''
        layerNumber = 1
        for layer in self.layers:
            tempString += ';T' + str(layerNumber) + '\n'
            tempString += ';M6\n'
            tempString += str(layer)
            layerNumber += 1
        return tempString
    