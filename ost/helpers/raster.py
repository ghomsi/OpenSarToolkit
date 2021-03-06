#! /usr/bin/env python
"""
This script provides wrapper functions for processing Sentinel-1 GRD products.
"""

# import stdlib modules
import os
import numpy as np

# geo libs
import gdal
import osr
import ogr
import fiona
import rasterio
import rasterio.mask


# script infos
__author__ = 'Andreas Vollrath'
__copyright__ = 'phi-lab, European Space Agency'

__license__ = 'GPL'
__version__ = '1.0'
__maintainer__ = 'Andreas Vollrath'
__email__ = ''
__status__ = 'Production'


def readFile(rasterfn):

    # open raster file
    raster = gdal.Open(rasterfn)

    # Get blocksizes for iterating over tiles (chuuks)
    myBlockSize = raster.GetRasterBand(1).GetBlockSize()
    x_block_size = myBlockSize[0]
    y_block_size = myBlockSize[1]

    # Get image sizes
    cols = raster.RasterXSize
    rows = raster.RasterYSize
    bands = raster.RasterCount

    # get datatype and transform to numpy readable
    data_type = raster.GetRasterBand(1).DataType
    data_type_name = gdal.GetDataTypeName(data_type)

    if data_type_name == "Byte":
        data_type_name = "uint8"

    print(' INFO: Importing {} bands from {}'.format(raster.RasterCount,
          rasterfn))

    geotransform = raster.GetGeoTransform()
    originX = geotransform[0]
    originY = geotransform[3]
    pixelWidth = geotransform[1]
    pixelHeight = geotransform[5]
    driver = gdal.GetDriverByName('GTiff')  # critical!!!!!!!!!!!!!!!!!!!!!!!
    ndv = raster.GetRasterBand(1).GetNoDataValue()

    # we need this for file creation
    outRasterSRS = osr.SpatialReference()
    outRasterSRS.ImportFromWkt(raster.GetProjectionRef())

    # we return a dict of all relevant values
    return {'xB': x_block_size, 'yB': y_block_size, 'cols': cols, 'rows': rows,
            'bands': bands, 'dt': data_type, 'dtn': data_type_name, 'ndv': ndv,
            'gtr': geotransform, 'oX': originX, 'oY': originY,
            'pW': pixelWidth, 'pH': pixelHeight, 'driver': driver,
            'outR': outRasterSRS}


def createFile(newRasterfn, cols, rows, bands, data_type, originX, originY,
               pixelWidth, pixelHeight, outRasterSRS, driver, ndv):

    outRaster = driver.Create(newRasterfn, cols, rows, bands, data_type,
                              options=[
                                      'TILED=YES',
                                      'BIGTIFF=IF_SAFER',
                                      'BLOCKXSIZE=128',
                                      'BLOCKYSIZE=128',
                                      'COMPRESS=LZW'
                                      ])

    outRaster.SetGeoTransform((originX, pixelWidth, 0, originY,
                               0, pixelHeight))
    outRaster.SetProjection(outRasterSRS.ExportToWkt())
    if ndv is not None:
        outRaster.GetRasterBand(1).SetNoDataValue(ndv)

    return outRaster


# write chunks of arrays to an already existent raster
def chunk2raster(outRasterfn, array_chunk, ndv, x, y, z):

    outRaster = gdal.Open(outRasterfn, gdal.GA_Update)
    outband = outRaster.GetRasterBand(z)

    # write to array
    outband.WriteArray(array_chunk, x, y, z)


def replaceValue(rasterfn, repValue, newValue):

    # open raster file
    raster = gdal.Open(rasterfn, gdal.GA_Update)

    # Get blocksizes for iterating over tiles (chuuks)
    myBlockSize = raster.GetRasterBand(1).GetBlockSize()
    x_block_size = myBlockSize[0]
    y_block_size = myBlockSize[1]

    # Get image sizes
    cols = raster.RasterXSize
    rows = raster.RasterYSize

    # loop through y direction
    for y in range(0, rows, y_block_size):
        if y + y_block_size < rows:
            ysize = y_block_size
        else:
            ysize = rows - y

        # loop throug x direction
        for x in range(0, cols, x_block_size):
            if x + x_block_size < cols:
                xsize = x_block_size
            else:
                xsize = cols - x

            rasterArray = np.array(raster.GetRasterBand(1).ReadAsArray(x, y,
                                   xsize, ysize))
            rasterArray[rasterArray <= np.float32(repValue)] = np.float32(
                                                                    newValue)

        raster.GetRasterBand(1).WriteArray(rasterArray, x, y)


def polygonize2Shp(inRaster, outShp, outEPSG=4326, mask=None):
    """
    This function takes an input raster and polygonizes it.

    :param inRaster: input raster file
    :param mask: mask file
    :param outShp: output shapefile
    :param srs: spatial reference system in EPSG code
    :return:
    """

    raster = gdal.Open(inRaster)
    srcBand = raster.GetRasterBand(1)

    if mask is not None:
        maskFile = gdal.Open(mask)
        maskBand = maskFile.GetRasterBand(1)
    else:
        maskBand = srcBand

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(outEPSG)

    dstLayername = outShp
    drv = ogr.GetDriverByName("ESRI Shapefile")
    dstDs = drv.CreateDataSource(dstLayername)
    dstLayer = dstDs.CreateLayer(dstLayername, srs=srs)
    gdal.Polygonize(srcBand, maskBand, dstLayer, -1, [], callback=None)


def outline(inFile, outFile, ndv=0, ltOption=False):
    '''
    This function returns the valid areas (i.e. non no-data areas) of a
    raster file as a shapefile.

    :param inFile: inpute raster file
    :param outFile: output shapefile
    :param ndv: no data value of the input raster
    :return:
    '''

    # get all the metadata from the stack
    geo_list = readFile(inFile)

    # create a temporary rasterfile which will be our mask
    createFile('{}.tif'.format(outFile), geo_list['cols'], geo_list['rows'],
               1, gdal.GDT_Byte, geo_list['oX'], geo_list['oY'],
               geo_list['pW'], geo_list['pH'], geo_list['outR'],
               gdal.GetDriverByName('GTiff'), ndv)

    raster = gdal.Open(inFile)
    myBlockSize = raster.GetRasterBand(1).GetBlockSize()
    x_block_size = myBlockSize[0]
    y_block_size = myBlockSize[1]

    # Get image sizes
    cols = raster.RasterXSize
    rows = raster.RasterYSize

    # loop through y direction
    for y in range(0, rows, y_block_size):
        if y + y_block_size < rows:
            ysize = y_block_size
        else:
            ysize = rows - y

        # loop throug x direction
        for x in range(0, cols, x_block_size):
            if x + x_block_size < cols:
                xsize = x_block_size
            else:
                xsize = cols - x

            # create the blocksized array
            rasterArray = np.empty((raster.RasterCount, ysize, xsize),
                                   dtype=np.float32)

            for i in range(raster.RasterCount):
                i += 0
                rasterArray[i, :, :] = np.array(
                        raster.GetRasterBand(i + 1).ReadAsArray(
                                x, y, xsize, ysize))

            # take care of nans
            where_are_NaNs = np.isnan(rasterArray)
            rasterArray[where_are_NaNs] = ndv

            minArray = np.min(rasterArray, axis=0)

            if ltOption is True:
                minArray[minArray <= ndv] = 0
            else:
                minArray[minArray == ndv] = 0

            minArray[minArray != 0] = 1

            chunk2raster('{}.tif'.format(outFile), minArray, 0, x, y, 1)

    # now let's polygonize
    polygonize2Shp('{}.tif'.format(outFile), outFile, 4326, '{}.tif'.format(
            outFile))
    os.remove('{}.tif'.format(outFile))


# convert dB to power
def convert2Pow(dB_array):

    pow_array = 10 ** (dB_array / 10)
    return pow_array


# convert power to dB
def convert2DB(pow_array):

    pow_array[pow_array < 0] = 0.0000001
    dB_array = 10 * np.log10(pow_array.clip(min=0.0000000000001))
    return dB_array


# rescale sar dB dat ot integer format
def scale2Int(float_array, minVal, maxVal, datatype):

    # set output min and max
    display_min = 1.
    if datatype == 'uint8':
        display_max = 255.
    elif datatype == 'uint16':
        display_max = 65535.

    a = minVal - ((maxVal - minVal)/(display_max - display_min))
    x = (maxVal - minVal)/(display_max - 1)

    float_array[float_array > maxVal] = maxVal
    float_array[float_array < minVal] = minVal

    int_array = np.round((float_array - a) / x).astype(datatype)

    return int_array


# rescale integer scaled sar data back to dB
def rescale2Float(int_array, data_type_name):

    if data_type_name == 'uint8':
        float_array = int_array.astype(float) * ( 35. / 254.) + (-30. - (35. / 254.))
    elif data_type_name == 'uint16':
        float_array = int_array.astype(float) * ( 35. / 65535.) + (-30. - (35. / 65535.))

    return float_array


def maskByShape(inFile, outFile, shpFile, toDB=False, dType='float32',
                minVal=0.000001, maxVal=1, ndv=None):

    # import shapefile geometries
    with fiona.open(shpFile, 'r') as shapefile:
        features = [feature['geometry'] for feature in shapefile]

    # import raster
    with rasterio.open(inFile) as src:
        outImage, outTransform = rasterio.mask.mask(src, features, crop=True)
        outMeta = src.meta.copy()
        outImage = np.ma.masked_where(outImage == ndv, outImage)

    # if to decibel should be applied
    if toDB is True:
        outImage = convert2DB(outImage)

    # if we scale to another d
    if dType != 'float32':

        if dType == 'uint8':
            outImage = scale2Int(outImage, minVal, maxVal, 'uint8')
        elif dType == 'uint16':
            outImage = scale2Int(outImage, minVal, maxVal, 'uint16')

    outMeta.update({'driver': 'GTiff', 'height': outImage.shape[1],
                    'width': outImage.shape[2], 'transform': outTransform,
                    'nodata': ndv, 'dtype': dType})

    with rasterio.open(outFile, 'w', **outMeta) as dest:
        dest.write(outImage)
