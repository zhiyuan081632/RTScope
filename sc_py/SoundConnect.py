'''
SoundConnect python interface.

Copyright: 2026-04-17 yueyue.nyy
'''

import os
import numpy as np
import ctypes
from ctypes import *
from numpy.ctypeslib import ndpointer


class SoundConnect():
    
    '''
    init algorithm
    libpath:            lib (dll, so) path
    confpath:           conf file path
    '''
    def __init__(self, libpath, confpath):
        super().__init__()
        
        self.lib = ctypes.cdll.LoadLibrary(libpath)
        
        #
        # register arg types
        #
        self.lib.SoundConnectPy_init.argtypes = [c_char_p]
        self.lib.SoundConnectPy_init.restype = c_void_p
        
        self.lib.SoundConnectPy_free.argtypes = [c_void_p]
        
        # init algorithm
        self.obj = self.lib.SoundConnectPy_init(c_char_p(confpath.encode('UTF-8')))
        
        self.lib.SoundConnectPy_version.restype = c_char_p
        
        self.lib.SoundConnectPy_licenceInfo.restype = c_char_p
        
        self.lib.SoundConnectPy_numMics.argtypes = [c_void_p]
        self.lib.SoundConnectPy_numMics.restype = c_int
        
        self.lib.SoundConnectPy_numRefs.argtypes = [c_void_p]
        self.lib.SoundConnectPy_numRefs.restype = c_int
        
        self.lib.SoundConnectPy_numPilots.argtypes = [c_void_p]
        self.lib.SoundConnectPy_numPilots.restype = c_int
        
        self.lib.SoundConnectPy_numIns.argtypes = [c_void_p]
        self.lib.SoundConnectPy_numIns.restype = c_int
        
        self.lib.SoundConnectPy_numOuts.argtypes = [c_void_p]
        self.lib.SoundConnectPy_numOuts.restype = c_int
        
        self.lib.SoundConnectPy_sampleRateIn.argtypes = [c_void_p]
        self.lib.SoundConnectPy_sampleRateIn.restype = c_int
        
        self.lib.SoundConnectPy_sampleRateOut.argtypes = [c_void_p]
        self.lib.SoundConnectPy_sampleRateOut.restype = c_int
        
        self.lib.SoundConnectPy_bitsPerSampleIn.argtypes = [c_void_p]
        self.lib.SoundConnectPy_bitsPerSampleIn.restype = c_int
        
        self.lib.SoundConnectPy_bitsPerSampleOut.argtypes = [c_void_p]
        self.lib.SoundConnectPy_bitsPerSampleOut.restype = c_int
        
        self.lib.SoundConnectPy_blockSizeIn.argtypes = [c_void_p]
        self.lib.SoundConnectPy_blockSizeIn.restype = c_int
        
        self.lib.SoundConnectPy_blockSizeOut.argtypes = [c_void_p]
        self.lib.SoundConnectPy_blockSizeOut.restype = c_int
        
        self.lib.SoundConnectPy_samplesPerBlockIn.argtypes = [c_void_p]
        self.lib.SoundConnectPy_samplesPerBlockIn.restype = c_int
        
        self.lib.SoundConnectPy_samplesPerBlockOut.argtypes = [c_void_p]
        self.lib.SoundConnectPy_samplesPerBlockOut.restype = c_int
        
        self.lib.SoundConnectPy_bytesPerBlockIn.argtypes = [c_void_p]
        self.lib.SoundConnectPy_bytesPerBlockIn.restype = c_int
        
        self.lib.SoundConnectPy_bytesPerBlockOut.argtypes = [c_void_p]
        self.lib.SoundConnectPy_bytesPerBlockOut.restype = c_int
        
        self.lib.SoundConnectPy_delay.argtypes = [c_void_p]
        self.lib.SoundConnectPy_delay.restype = c_float
        
        numpilots = self.lib.SoundConnectPy_numPilots(self.obj)
        self.lib.SoundConnectPy_setPilot.argtypes = [
            c_void_p, 
            ndpointer(dtype = c_float, shape = (numpilots, ))]
        
        spbin = self.lib.SoundConnectPy_samplesPerBlockIn(self.obj)
        spbout = self.lib.SoundConnectPy_samplesPerBlockOut(self.obj)
        self.lib.SoundConnectPy_processFloat.argtypes = [
            c_void_p, 
            ndpointer(dtype = c_float, shape = (spbin, )), 
            ndpointer(dtype = c_float, shape = (spbout, ))]
        
        self.lib.SoundConnectPy_processByte.argtypes = [c_void_p, c_char_p, c_char_p]
        
        #
        # ssl
        #
        self.lib.SoundConnectPy_sslEstimate.argtypes = [c_void_p, c_int, POINTER(c_float), POINTER(c_float), POINTER(c_float)]
        self.lib.SoundConnectPy_sslEstimate.restype = c_int
        
        self.lib.SoundConnectPy_sslClear.argtypes = [c_void_p, c_int]
        
        #
        # kws
        #
        self.lib.SoundConnectPy_kwsNumKeywords.argtypes = [c_void_p]
        self.lib.SoundConnectPy_kwsNumKeywords.restype = c_int
        
        self.lib.SoundConnectPy_kwsIsSpotted.argtypes = [c_void_p]
        self.lib.SoundConnectPy_kwsIsSpotted.restype = c_char
        
        self.lib.SoundConnectPy_kwsSpottedKeywordIndex.argtypes = [c_void_p]
        self.lib.SoundConnectPy_kwsSpottedKeywordIndex.restype = c_int
        
        self.lib.SoundConnectPy_kwsConfidence.argtypes = [c_void_p]
        self.lib.SoundConnectPy_kwsConfidence.restype = c_float
        
        self.lib.SoundConnectPy_kwsKeywordOffset.argtypes = [c_void_p]
        self.lib.SoundConnectPy_kwsKeywordOffset.restype = c_float
        
        self.lib.SoundConnectPy_kwsKeywordLength.argtypes = [c_void_p]
        self.lib.SoundConnectPy_kwsKeywordLength.restype = c_float
        
        self.lib.SoundConnectPy_kwsBestChannel.argtypes = [c_void_p]
        self.lib.SoundConnectPy_kwsBestChannel.restype = c_int
        
        #
        # vp
        #
        self.lib.SoundConnectPy_vpVoiceprintSize.argtypes = [c_void_p]
        self.lib.SoundConnectPy_vpVoiceprintSize.restype = c_int
        vpsize = self.lib.SoundConnectPy_vpVoiceprintSize(self.obj)
        
        self.lib.SoundConnectPy_vpGetVoiceprint.argtypes = [c_void_p, c_int]
        self.lib.SoundConnectPy_vpGetVoiceprint.restype = ndpointer(
            dtype = c_float, shape = (vpsize, ))
        
        self.lib.SoundConnectPy_vpSetVoiceprint.argtypes = [
            c_void_p, 
            c_int, 
            c_float, 
            ndpointer(dtype = c_float, shape = (vpsize, ))
            ]
        
        self.lib.SoundConnectPy_vpExtractVoiceprint.argtypes = [c_void_p, c_int, c_float, c_float]
        self.lib.SoundConnectPy_vpExtractVoiceprint.restype = ndpointer(
            dtype = c_float, shape = (vpsize, ))
        
        self.lib.SoundConnectPy_vpVerify.argtypes = [
            c_void_p, 
            ndpointer(dtype = c_float, shape = (vpsize, )), 
            c_int, 
            POINTER(c_float)
            ]
        self.lib.SoundConnectPy_vpVerify.restype = c_char
        
        self.lib.SoundConnectPy_vpSearch.argtypes = [
            c_void_p, 
            ndpointer(dtype = c_float, shape = (vpsize, )), 
            POINTER(c_float)
            ]
        self.lib.SoundConnectPy_vpSearch.restype = c_int
        
        self.lib.SoundConnectPy_vpGetLevel.argtypes = [c_void_p]
        self.lib.SoundConnectPy_vpGetLevel.restype = c_float
        
        self.lib.SoundConnectPy_vpSetLevel.argtypes = [c_void_p, c_float]
    
    
    '''
    release algorithm instance
    '''
    def __del__(self):
        self.lib.SoundConnectPy_free(self.obj)
    
    
    '''
    get version info
    '''
    def version(self):
        return self.lib.SoundConnectPy_version().decode('UTF-8')
    
    
    '''
    get licence info
    '''
    def licenceInfo(self):
        return self.lib.SoundConnectPy_licenceInfo().decode('UTF-8')
    
    
    '''
    get the no. of mic channels
    '''
    def numMics(self):
        return self.lib.SoundConnectPy_numMics(self.obj)
    
    
    '''
    get the no. of reference channels
    '''
    def numRefs(self):
        return self.lib.SoundConnectPy_numRefs(self.obj)
    
    
    '''
    get the no. of pilot channels
    '''
    def numPilots(self):
        return self.lib.SoundConnectPy_numPilots(self.obj)
    
    
    '''
    get the no. of input channels
    '''
    def numIns(self):
        return self.lib.SoundConnectPy_numIns(self.obj)
    
    
    '''
    get the no. of output channels
    '''
    def numOuts(self):
        return self.lib.SoundConnectPy_numOuts(self.obj)
    
    
    '''
    get the input sample rate (Hz)
    '''
    def sampleRateIn(self):
        return self.lib.SoundConnectPy_sampleRateIn(self.obj)
    
    
    '''
    get the output sample rate (Hz)
    '''
    def sampleRateOut(self):
        return self.lib.SoundConnectPy_sampleRateOut(self.obj)
    
    
    '''
    get no. of bits per sample for input signals
    '''
    def bitsPerSampleIn(self):
        return self.lib.SoundConnectPy_bitsPerSampleIn(self.obj)
    
    
    '''
    get no. of bits per sample for output signals
    '''
    def bitsPerSampleOut(self):
        return self.lib.SoundConnectPy_bitsPerSampleOut(self.obj)
    
    
    '''
    get input block size (no. of frames)
    '''
    def blockSizeIn(self):
        return self.lib.SoundConnectPy_blockSizeIn(self.obj)
    
    
    '''
    get output block size (no. of frames)
    '''
    def blockSizeOut(self):
        return self.lib.SoundConnectPy_blockSizeOut(self.obj)
    
    
    '''
    get the no. of samples in an input block: numins * blocksizein
    '''
    def samplesPerBlockIn(self):
        return self.lib.SoundConnectPy_samplesPerBlockIn(self.obj)
    
    
    '''
    get the no. of samples in an output block: numouts * blocksizeout
    '''
    def samplesPerBlockOut(self):
        return self.lib.SoundConnectPy_samplesPerBlockOut(self.obj)
    
    
    '''
    get the no. of bytes in an input block: numins * blocksizein * nbitsin / 8
    '''
    def bytesPerBlockIn(self):
        return self.lib.SoundConnectPy_bytesPerBlockIn(self.obj)
    
    
    '''
    get the no. of bytes in an output block: numouts * blocksizeout * nbitsout / 8
    '''
    def bytesPerBlockOut(self):
        return self.lib.SoundConnectPy_bytesPerBlockOut(self.obj)
    
    
    '''
    get time delay (second) introduced by the algorithm
    '''
    def delay(self):
        return self.lib.SoundConnectPy_delay(self.obj)
    
    
    '''
    set pilot information, this must be set before process()
    pilot:              pilot information, [numpilots], range [0, 1]
    '''
    def setPilot(self, pilot):
        self.lib.SoundConnectPy_setPilot(self.obj, pilot)
    
    
    '''
    process one data block
    datain:             input multi-channel (mic + ref) data
    dataout:            output data, NULL supported
    '''
    def processFloat(self, datain, dataout):
        return self.lib.SoundConnectPy_processFloat(self.obj, datain, dataout)
    
    
    '''
    process one data block
    datain:             input multi-channel (mic + ref) data
    dataout:            output data, NULL supported
    '''
    def processByte(self, datain, dataout):
        return self.lib.SoundConnectPy_processByte(self.obj, datain, dataout)
    
    
    '''
    estimate sound source location
    n:                  output channel index
    return:             [zone index, azimuth (degree), elevation (degree), distance (m)]
    '''
    def sslEstimate(self, n):
        az = c_float()
        el = c_float()
        d = c_float()
        
        zoneidx = self.lib.SoundConnectPy_sslEstimate(self.obj, n, byref(az), byref(el), byref(d))
        
        return [zoneidx, az.value, el.value, d.value]
    
    
    '''
    clear the former sound source localization result
    n:                  output channel index
    '''
    def sslClear(self, n):
        self.lib.SoundConnectPy_sslClear(self.obj, n)
    
    
    '''
    get the no. of keywords
    '''
    def kwsNumKeywords(self):
        return self.lib.SoundConnectPy_kwsNumKeywords(self.obj)    
    
    
    '''
    to see if a keyword is found
    return:             0: not spotted
                        1: spotted
                        2: best end
                        3: both spotted and best end
                        4: suspect keyword (both spot and bestend)
    '''
    def kwsIsSpotted(self):
        return self.lib.SoundConnectPy_kwsIsSpotted(self.obj)
    
    
    '''
    get the keyword index of the last spot
    '''
    def kwsSpottedKeywordIndex(self):
        return self.lib.SoundConnectPy_kwsSpottedKeywordIndex(self.obj)
    
    
    '''
    get the confidence of last spot
    '''
    def kwsConfidence(self):
        return self.lib.SoundConnectPy_kwsConfidence(self.obj)
    
    
    '''
    get relative keyword start time (second) of last spot
    return:             negative value, means before current time
    '''
    def kwsKeywordOffset(self):
        return self.lib.SoundConnectPy_kwsKeywordOffset(self.obj)
    
    
    '''
    get keyword length (second) of last spot
    '''
    def kwsKeywordLength(self):
        return self.lib.SoundConnectPy_kwsKeywordLength(self.obj)
    
    
    '''
    get best channel index
    '''
    def kwsBestChannel(self):
        return self.lib.SoundConnectPy_kwsBestChannel(self.obj)
    
    
    '''
    get voiceprint vector size
    '''
    def vpVoiceprintSize(self):
        return self.lib.SoundConnectPy_vpVoiceprintSize(self.obj)
    
    
    '''
    get voiceprint reference
    idx:                speaker index
    return:             voiceprint, [vpsize], data is not copied
    '''
    def vpGetVoiceprint(self, idx):
        return self.lib.SoundConnectPy_vpGetVoiceprint(self.obj, idx)
    
    
    '''
    set voiceprint
    idx:                speaker index
    forget:             forgetting factor [0, 1], update as:
                        old = forget * old + (1 - forget) * new
    vp:                 voiceprint, [vpsize], data is copied, NULL for zero vector
    '''
    def vpSetVoiceprint(self, idx, forget, vp):
        return self.lib.SoundConnectPy_vpSetVoiceprint(self.obj, idx, forget, vp)
    
    
    '''
    calculate voiceprint by recently buffered data
    n:                  output channel index
    offset:             extraction offset (s), nonpositive,
                        0: current time,
                        -tau: tau seconds before current
    len:                extraction length (s),
                        negative: entire duration since clear
                        0: current embedding
    return:             voiceprint, [vpsize]
    '''
    def vpExtractVoiceprint(self, n, offset, len):
        return self.lib.SoundConnectPy_vpExtractVoiceprint(self.obj, n, offset, len)
    
    
    '''
    voiceprint verification
    vp:                 unknown voiceprint, NULL to use extracted voiceprint
    idx:                expected speaker index
    return:             true if the voiceprint belongs to the same speaker, confidence
    '''
    def vpVerify(self, vp, idx):
        confidence = c_float()
        isverified = self.lib.SoundConnectPy_vpVerify(self.obj, vp, idx, byref(confidence))
        return isverified, confidence
    
    
    '''
    find speaker index by voiceprint
    vp:                 voiceprint, NULL to use extracted voiceprint
    return:             -1 if not found, confidence
    '''
    def vpSearch(self, vp):
        confidence = c_float()
        spkidx = self.lib.SoundConnectPy_vpSearch(self.obj, vp, byref(confidence))
        return spkidx, confidence
    
    
    '''
    get voiceprint verification threshold
    '''
    def vpGetLevel(self):
        return self.lib.SoundConnectPy_vpGetLevel(self.obj)
    
    
    '''
    set voiceprint verification threshold
    thres:              the threshold
    '''
    def vpSetLevel(self, thres):
        self.lib.SoundConnectPy_vpSetLevel(self.obj, thres)
    
    
if __name__ == '__main__':
    libpath = 'D:/data/programming/eclipse-workspace/SoundConnect/Debug/SoundConnect.dll'
    # libpath = './lib/RaspberryPi/libSoundConnect.so'
    confpath = 'D:/data/programming/eclipse-workspace/SoundConnect/conf/default.conf'
    # confpath = './conf/vptse_mugua.conf'
    
    sc = SoundConnect(libpath, confpath)
    
    print(sc.version())
    print(sc.licenceInfo())
    print('numMics:', sc.numMics())
    print('numRefs:', sc.numRefs())
    print('numPilots:', sc.numPilots())
    print('numIns:', sc.numIns())
    print('numOuts:', sc.numOuts())
    print('sampleRateIn:', sc.sampleRateIn())
    print('sampleRateOut:', sc.sampleRateOut())
    print('bitsPerSampleIn:', sc.bitsPerSampleIn())
    print('bitsPerSampleOut:', sc.bitsPerSampleOut())
    print('blockSizeIn:', sc.blockSizeIn())
    print('blockSizeOut:', sc.blockSizeOut())
    print('samplesPerBlockIn:', sc.samplesPerBlockIn())
    print('samplesPerBlockOut:', sc.samplesPerBlockOut())
    print('bytesPerBlockIn:', sc.bytesPerBlockIn())
    print('bytesPerBlockOut:', sc.bytesPerBlockOut())
    print('delay:', sc.delay())
        
    del sc
    print('Completed.')
