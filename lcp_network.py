# -*- coding: utf-8 -*-
"""
/***************************************************************************
 LCPNetwork
                                 A QGIS plugin
 Compute the LCP network from multiple origins to multiple destinations
                              -------------------
        begin                : 2016-11-19
        git sha              : $Format:%H$
        copyright            : (C) 2016 by Xavier Rubio-Campillo
        email                : xavier.rubio@ed.ac.uk
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from __future__ import print_function
from __future__ import absolute_import
from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import range
from builtins import object
from qgis.PyQt.QtCore import QSettings, QTranslator, qVersion, QCoreApplication
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox, QProgressBar
from qgis.PyQt.QtGui import QIcon 

from qgis.core import QgsMapLayer, QgsProject, Qgis, QgsPointXY, QgsWkbTypes, QgsCoordinateReferenceSystem

## multithread
from concurrent import futures 
from threading import current_thread 
from time import sleep


# Initialize Qt resources from file resources.py
from . import resources
# Import the code for the dialog
from .lcp_network_dialog import LCPNetworkDialog
import os
from osgeo import gdal

import numpy as np
from qgis.core import QgsMessageLog
from qgis.core import QgsRasterLayer
from qgis.core import QgsVectorLayer
from qgis.core import QgsContrastEnhancement
from qgis.core import QgsFeature
from qgis.core import QgsGeometry

import sys
import numpy.ma as ma

import timeit

class LCPNetwork(object):
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'LCPNetwork_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)


        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Least-Cost-Paths Network')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'LCPNetwork')
        self.toolbar.setObjectName(u'LCPNetwork')

        # Create the dialog (after translation) and keep reference
        self.dlg = LCPNetworkDialog()
#        self.dlg.outputFile.clear()
#      self.dlg.browseOutput.clicked.connect(self.selectOutputFile)

    """
    def selectOutputFile(self):
        fileName = QFileDialog.getSaveFileName(self.dlg, "Select output file ","", '*.tif')
        self.dlg.outputFile.setText(fileName)
    """

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('LCPNetwork', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/LCPNetwork/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'&LCP Network'),
            callback=self.run,
            parent=self.iface.mainWindow())


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&Least-Cost-Paths Network'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar


    def loadLayers(self): 
        layers = self.iface.mapCanvas().layers()
        for layer in layers:
            if layer.type() == QgsMapLayer.RasterLayer:
                self.dlg.baseLayer.addItem(layer.name(), layer.id())
            elif layer.geometryType() == QgsWkbTypes.PointGeometry:
                self.dlg.origins.addItem(layer.name(), layer.id())
                self.dlg.destinations.addItem(layer.name(), layer.id())
                
    def clearUI(self):
        self.dlg.baseLayer.clear()
        self.dlg.origins.clear()
        self.dlg.destinations.clear()

    def run(self):
        """Run method that performs all the real work"""
        self.clearUI()
        self.loadLayers()
        # show the dialog
        self.dlg.show()
        # Run the dialog event loop
        result = self.dlg.exec_()
        # See if OK was pressed
        if result:
            self.runAlgorithm()

    def loadPoints(self):   
        indexO = self.dlg.origins.currentIndex()
        layerO = self.dlg.origins.itemData(indexO)
        originLayer = QgsProject.instance().mapLayer(layerO)

        indexD = self.dlg.destinations.currentIndex()
        layerD = self.dlg.destinations.itemData(indexD)
        destinationLayer = QgsProject.instance().mapLayer(layerD)

        return originLayer,destinationLayer

    def loadBaseRaster(self):
        index = self.dlg.baseLayer.currentIndex()
        layer = self.dlg.baseLayer.itemData(index)
        path= str(QgsProject.instance().mapLayer(layer).dataProvider().dataSourceUri())
        return gdal.Open(path)

    def getCell( self, point ):
        """ get local coordinates for point based on baseRaster transform """
        topLeft = QgsPointXY(self.transform[0], self.transform[3])

        pointInRaster = QgsPointXY(point.x() - topLeft.x(), topLeft.y() - point.y())
        # swap axes
        cell = QgsPointXY(int(pointInRaster.y()/-self.transform[5]), int(pointInRaster.x()/self.transform[1]))
        return cell

    def getGlobalPos(self, localPos ):
        """ get global coordinates for local point based on baseRaster transform """
        topLeft = QgsPointXY(self.transform[0], self.transform[3])

        # swap axes
        pos = QgsPointXY(localPos.y()*(-self.transform[5]), localPos.x()*(-self.transform[1]))
        globalPoint = QgsPointXY(pos.x()+topLeft.x(), pos.y()+topLeft.y())
        
        return globalPoint

    def isInside(self, cell, surface ):
        """ returns true if cellin surface or false if it is not """
        if cell.x() < 0 or cell.x() >= surface.RasterYSize or cell.y() <0 or cell.y() >= surface.RasterXSize :
            return False
        return True


    def getNeighbors(self, point, surface):
        """ current: only four direct neighbors """
        neighbors = list()

        for i in range(-1,2):
            for j in range(-1,2):
                candidate = QgsPointXY(point.x()+i, point.y()+j)
                if self.isInside(candidate, surface):
                    neighbors.append(candidate)
        return neighbors            

    def getMinimumUnvisited(self, visited, distances ):

        # set to null values of already visited (kind of a mask)
        possibleValues = ma.masked_array(distances, mask=visited, )

#       for i in range(len(possibleValues)):
#            QgsMessageLog.logMessage("value "+str(i)+" visited: "+str(visited[i])+" distances: "+str(distances[i])+" -> "+str(possibleValues[i]), tag="LCPNetwork", level=Qgis.Info)

        # no available values because everything is already masked
        if len(possibleValues[~possibleValues.mask])==0:
            return None 

        mininimumValues = np.nanmin(possibleValues[~possibleValues.mask])           
#        QgsMessageLog.logMessage("minimum values: "+str(mininimumValues), "LCPNetwork")
        candidates = np.where(possibleValues == mininimumValues) 

#        for i in range(len(candidates[0])):
#            QgsMessageLog.logMessage("\tcandidate "+str(i)+" -> "+str(candidates[0][i])+"/"+str(candidates[1][i]), tag="LCPNetwork", level=Qgis.Info)

        if len(candidates[0]) == 0:
            return None

        selected = np.random.randint(len(candidates[0]))
        return QgsPointXY(candidates[0][selected], candidates[1][selected])


    def isDiagonal(self, centre, candidate):
        if centre.x()==candidate.x() or centre.y()==candidate.y():
            return False
        
        return True            

    def computeCost( self, originGeo, baseRaster, logMessageFile):
        origin = self.getCell(originGeo)
        costValues = baseRaster.GetRasterBand(1).ReadAsArray()

        if not self.isInside(origin, baseRaster):
            logMessage = "error - origin point: "+str(originGeo.x())+"/"+str(originGeo.y())+" local coords: "+str(origin.x())+"/"+str(origin.y())+" falls outside raster limits"
            QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Warning)
            logMessageFile.write(logMessage+"\n")
            return None

        # initialize helper matrices
        width,height = costValues.shape
        visited = np.full([width, height], False, dtype=bool)
        distances = np.full([width,height], np.nan, dtype=np.float32)

        # initialize current
        current = origin

        visited[int(current.x()), int(current.y())] = True
        distances[int(current.x()), int(current.y())] = 0

        nodata = int(baseRaster.GetRasterBand(1).GetNoDataValue())
        stats= baseRaster.GetRasterBand(1).GetStatistics(0,1)
        maxValue = stats[1]

        candidates = True
        i = 0
        while candidates==True: 
            i = i+1
            neighbors = self.getNeighbors(current, baseRaster)
            #QgsMessageLog.logMessage("iteration: "+str(i)+" current: "+str(current.x())+"/"+str(current.y())+" with num neighbors: "+str(len(neighbors)), tag="LCPNetwork", level=Qgis.Info)
            
            for neighbor in neighbors:
                #QgsMessageLog.logMessage("\tchecking neighbour: "+str(neighbor.x())+"/"+str(neighbor.y()), tag="LCPNetwork", level=Qgis.Info)
                
                cost =  costValues[int(neighbor.x()), int(neighbor.y())]
                # null values will be slightly higher than the maximum cost in the map
                # they have a slightly random value so they don't generate exactly the same costs on the final map
                if cost == nodata:
                    cost = maxValue*1.01
                # diagonals cost more
                elif self.isDiagonal(current,neighbor):
                    cost = cost*np.sqrt(2)

                tentativeDistance = distances[int(current.x()), int(current.y())] + cost
                #QgsMessageLog.logMessage("\ttentative distance: "+str(tentativeDistance)+" with distance: "+str(distances[int(current.x()), int(current.y())]) + " and cost: "+str(cost), tag="LCPNetwork", level=Qgis.Info)
                # cost can never be negative
                if tentativeDistance < 0:
                    tentativeDistance = 0
                if np.isnan(distances[int(neighbor.x()), int(neighbor.y())]) or distances[int(neighbor.x()), int(neighbor.y())] > tentativeDistance:
                    #QgsMessageLog.logMessage("\tchanging distance!", tag="LCPNetwork", level=Qgis.Info)
                    distances[int(neighbor.x()), int(neighbor.y())] = tentativeDistance

            visited[int(current.x()), int(current.y())] = True

            current = self.getMinimumUnvisited(visited, distances)
            if current is None:
                candidates = False
        
        logMessage = "finished with num. iterations: "+str(i)   
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")
        return distances

    def getPath( self, current, origin, baseRaster, costMap, logMessageFile, pathLine):

        if not self.isInside(origin, baseRaster) or not self.isInside(current, baseRaster):
            return None

#        logMessage = "getting path from current: "+str(current.x())+"/"+str(current.y())+" to origin: "+str(origin.x())+"/"+str(origin.y())
#        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
#        logMessageFile.write(logMessage+"\n")
            
        pathLine.append(current)

        # finished!
        if current==origin:
            return pathLine
              
        minValue = costMap[int(current.x()), int(current.y())]

        neighbors = self.getNeighbors(current, baseRaster)

        candidates = []

        for neighbor in neighbors:
     
#            logMessage = "\t\t\tchecking neighbor: "+str(neighbor.x())+"/"+str(neighbor.y())
#            QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
#            logMessageFile.write(logMessage+"\n")

            # if already in path:
            alreadyInPath = False 
            for pathPoint in pathLine:
                if pathPoint.sqrDist(neighbor)<1.0:
                    alreadyInPath = True
                    break

            if alreadyInPath:  
#                logMessage = "\t\t\tneighbor is already in path so it is ignored"
#                QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
#                logMessageFile.write(logMessage+"\n")
                continue

#           logMessage = "\t\t\tcost map: "+str(costMap[int(neighbor.x()),int(neighbor.y())])
#            QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
#            logMessageFile.write(logMessage+"\n")

            if costMap[int(neighbor.x()),int(neighbor.y())] < minValue:
                candidates = []
                candidates.append(neighbor)
                minValue = costMap[int(neighbor.x()),int(neighbor.y())]
            elif costMap[int(neighbor.x()),int(neighbor.y())] == minValue:
                candidates.append(neighbor)

        if len(candidates)==0:
            return None

        for candidate in candidates:
            fullPath = self.getPath(candidate, origin, baseRaster, costMap, logMessageFile, pathLine)
            if fullPath!=None:
                return fullPath

        return None                
                
    def getGlobalPath( self, originGeo, destinationGeo, baseRaster, costMap, logMessageFile):
    
        origin = self.getCell(originGeo)
        destination = self.getCell(destinationGeo)
            
        if not self.isInside(destination, baseRaster):
            logMessage = "destination not inside base raster!" 
            QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
            logMessageFile.write(logMessage+"\n")
            return None
        
        logMessage = "getting path from "+format(originGeo.x(), ".2f")+"/"+format(originGeo.y(), ".2f")+" to: "+format(destinationGeo.x(),".2f")+"/"+format(destinationGeo.y(),".2f")
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")

#        logMessage = "local coords from "+str(origin.x())+"/"+str(origin.y())+" to: "+str(destination.x())+"/"+str(destination.y())
#        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
#        logMessageFile.write(logMessage+"\n")

        # recursive function to extract the path from the cost map 
        # recursivity is used here to backtrack if you have 2 cells with the exact same accumulated cost but one is not a correct path
        sys.setrecursionlimit(1000000)

        initPathLine = []
        pathLine = self.getPath(destination, origin, baseRaster, costMap, logMessageFile, initPathLine)

        globalPath = []
        for localPoint in pathLine:
            globalPath.append(self.getGlobalPos(localPoint))

        return globalPath


    def storeCostMap(self, costMap, baseRaster, index):    
        outputName = os.path.dirname(__file__)+"/distances"+self._id+"_"+str(index)+".tif"
        newRaster = gdal.GetDriverByName('GTiff').Create(outputName, baseRaster.RasterXSize, baseRaster.RasterYSize, 1, gdal.GDT_Float32)
        newRaster.SetProjection(self.projection)
        newRaster.SetGeoTransform(self.transform)

        newRaster.GetRasterBand(1).WriteArray(costMap,0,0)
        newRaster.GetRasterBand(1).SetNoDataValue(np.nan)
        newRaster.GetRasterBand(1).FlushCache()
        newRaster = None        

    def computeOnePath(self, point, index, start, baseRaster, destinations, lcps, logMessageFile):
        # compute cost map for the entire area
        startCost = timeit.default_timer()
 
        logMessage = "%.2f"%(timeit.default_timer()-start)+" - id "+self._id+" thread: "+current_thread().name+" computing cost map from source point: "+str(index+1)+" at position: "+format(point.x(), ".2f")+"/"+format(point.y(), ".2f");
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")
      
        distances = self.computeCost(point, baseRaster, logMessageFile)

        logMessage = "\t%.2f"%(timeit.default_timer()-start)+" - Done! seconds to compute cost map: " + str("%.2f"%(timeit.default_timer()-startCost))
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")
        
        if distances is None:
            QMessageBox.information(None, "ERROR!", "Cost map could not be computed for point: "+str(index), tag="LCPNetwork", level=Qgis.Warning)
            return "error"

        self.storeCostMap(distances, baseRaster, index)   
        name = os.path.dirname(__file__)+"/distances"+self._id+"_"+str(index)+".tif"
        distanceBase = gdal.Open(name)
        
        distances = np.array(distanceBase.GetRasterBand(1).ReadAsArray())

        logMessage = "\t%.2f"%(timeit.default_timer()-start)+" thread: "+current_thread().name+" - cost map stored; estimating least-cost paths..."
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")
    
        destIndex = 1
        for destination in destinations:
            if destination == point:
                continue
            
            logMessage = "\t\t%.2f"%(timeit.default_timer()-start)+" - estimating path to dest: "+str(destIndex)+"/"+str(len(destinations))+" at pos:" +format(destination.x(), ".2f")+"/"+format(destination.y(), ".2f")
            QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
            logMessageFile.write(logMessage+"\n")
            pathLine = self.getGlobalPath(point, destination, baseRaster, distances, logMessageFile)
            if pathLine is None:
                QMessageBox.information(None, "ERROR!", "Route could not be found for destination: "+str(destIndex), tag="LCPNetwork", level=Qgis.Warning)
                return
            
            lcp = QgsFeature()
            ## set geometry from the list of QgsPointXY's to the feature
            lcp.setGeometry(QgsGeometry.fromPolylineXY(pathLine))
            lcps.append(lcp)
            destIndex = destIndex+1
        
        logMessage = "%.2f"%(timeit.default_timer()-start)+" thread: "+current_thread().name+" - computation finished for source point: "+str(index+1)
        QgsMessageLog.logMessage(logMessage,  tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")
        
        return "%.2f"%(timeit.default_timer()-start)+" - id "+self._id+" thread: "+current_thread().name+" finished for index: "+str(index)

    def runAlgorithm(self):
        start = timeit.default_timer()
        self._id = str(np.random.randint(1, 5000))
        logMessageFile = open(os.path.dirname(__file__)+"/logLCP"+self._id+".txt", "w")

        logMessage = "LCPNetwork plugin init - loading points and base raster layers with id: "+self._id
        QgsMessageLog.logMessage(logMessage,  tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")

        origins,destinations = self.loadPoints()
        baseRaster = self.loadBaseRaster()

        logMessage = "computing "+str(origins.featureCount())+" origin points towards "+str(destinations.featureCount())+" destinations"
        QgsMessageLog.logMessage(logMessage,  tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")

        self.transform = baseRaster.GetGeoTransform()
        self.projection = baseRaster.GetProjection()

        nodata = baseRaster.GetRasterBand(1).GetNoDataValue()  

        logMessage = "loading cost map with nodata value "+str(nodata) 
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")

        topLeft = QgsPointXY(self.transform[0], self.transform[3])
    
        pointsListO = []
        for point in origins.getFeatures():
            pointsListO.append(point.geometry().asPoint())
  
        pointsListD = []
        for point in destinations.getFeatures():
            pointsListD.append(point.geometry().asPoint())

        ## create the list of lcps
        lcps = []

        numThreads = os.cpu_count()
        logMessage = "creating "+str(numThreads)+" threads"
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")

        pool = futures.ThreadPoolExecutor(numThreads)
        index = 0
        results = []
        for source in pointsListO:
            results.append(pool.submit(self.computeOnePath, source, index, start, baseRaster, pointsListD, lcps, logMessageFile))
            index = index + 1 
          
        for future in futures.as_completed(results):     
            logMessageFile.write(future.result()+"\n")
 
        logMessage = "all lcps computed at time: " + str("%.2f"%(timeit.default_timer()-start))
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")

        # same CRS than base raster cost map
        crs = QgsCoordinateReferenceSystem()
        crs.createFromString(baseRaster.GetProjection())

        for i in range(index):
            outputName = os.path.dirname(__file__)+"/distances"+self._id+"_"+str(i)+".tif"
            newRasterQGIS = QgsRasterLayer(outputName, "distances"+self._id+"_"+str(i))
            newRasterQGIS.setContrastEnhancement(QgsContrastEnhancement.StretchToMinimumMaximum)
            newRasterQGIS.setCrs(crs)
            QgsProject.instance().addMapLayer(newRasterQGIS)

        # add the list of lcps to the network layer
        network = self.iface.addVectorLayer("LineString?crs="+crs.authid(), "least cost path network", "memory")
        network.dataProvider().addFeatures(lcps)
        
        logMessage = "LCPNetwork plugin finished! time (sec.): " + str("%.2f"%(timeit.default_timer()-start))
        QgsMessageLog.logMessage(logMessage, tag="LCPNetwork", level=Qgis.Info)
        logMessageFile.write(logMessage+"\n")
        logMessageFile.close()


