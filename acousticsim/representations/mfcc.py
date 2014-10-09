from numpy import (pad,log,array,zeros, floor,exp,sqrt,dot,arange,
                    hanning,sin, pi,linspace,log10,round,maximum,minimum,
                    sum,cos,spacing,diag,ceil)
from numpy.fft import fft

from acousticsim.representations.base import Representation
from acousticsim.representations.helper import preproc
from acousticsim.representations.specgram import to_powerspec

from scipy.fftpack import dct

def freqToMel(freq):
    """Convert a value in Hertz to a value in mel.

    Parameters
    ----------
    freq : numeric
        Frequency value in Hertz to convert.

    Returns
    -------
    float
        Frequency value in mel.

    """

    return 2595 * log10(1+freq/700.0)

def melToFreq(mel):
    """Convert a value in mel to a value in Hertz.

    Parameters
    ----------
    mel : numeric
        Frequency value in mel to convert.

    Returns
    -------
    float
        Frequency value in Hertz.

    """

    return 700*(10**(mel/2595.0)-1)


def dct_spectrum(spec):
    """Convert a spectrum into a cepstrum via type-III DCT (following HTK).

    Parameters
    ----------
    spec : array
        Spectrum to perform a DCT on.

    Returns
    -------
    array
        Cepstrum of the input spectrum.

    """
    ncep=spec.shape[0]
    dctm = zeros((ncep,ncep))
    for i in range(ncep):
        dctm[i,:] = cos(i * arange(1,2*ncep,2)/(2*ncep) * pi) * sqrt(2/ncep)
    dctm = dctm * 0.230258509299405
    cep =  dot(dctm , (10*log10(spec + spacing(1))))
    return cep

class Mfcc(Representation):
    def __init__(self, filepath, freq_lims, num_coeffs, win_len,
                        time_step, num_filters = 26, use_power = False,
                        attributes={}):
        Representation.__init__(self,filepath, freq_lims, attributes)
        self._num_coeffs = num_coeffs
        self._win_len = win_len
        self._time_step = time_step
        self._num_filters = 26
        self._use_power = use_power

        self.process()

    def filter_bank(self,nfft):
        """Construct a mel-frequency filter bank.

        Parameters
        ----------
        nfft : int
            Number of points in the FFT.
        nfilt : int
            Number of mel filters.
        minFreq : int
            Minimum frequency in Hertz.
        maxFreq : int
            Maximum frequency in Hertz.
        sr : int
            Sampling rate of the sampled waveform.

        Returns
        -------
        array
            Filter bank to multiply an FFT spectrum to create a mel-frequency
            spectrum.

        """

        nfilt = self._num_filters

        sr = self._sr

        minMel = freqToMel(self._freq_lims[0])
        maxMel = freqToMel(self._freq_lims[1])
        melPoints = linspace(minMel,maxMel,nfilt+2)
        binfreqs = melToFreq(melPoints)
        bins = round((nfft-1)*binfreqs/sr)

        fftfreqs = arange(int(nfft/2+1))/nfft * sr

        fbank = zeros((nfilt,int(nfft/2 +1)))
        for i in range(nfilt):
            fs = binfreqs[i+arange(3)]
            fs = fs[1] + (fs - fs[1])
            loslope = (fftfreqs - fs[0])/(fs[1] - fs[0])
            highslope = (fs[2] - fftfreqs)/(fs[2] - fs[1])
            fbank[i,:] = maximum(zeros(loslope.shape),minimum(loslope,highslope))
        #fbank = fbank / max(sum(fbank,axis=1))
        return fbank.transpose()

    def process(self):
        """Generate MFCCs in the style of HTK from a full path to a .wav file.

        Parameters
        ----------
        filename : str
            Full path to .wav file to process.
        freq_lims : tuple
            Minimum and maximum frequencies in Hertz to use.
        num_coeffs : int
            Number of coefficients of the cepstrum to return.
        win_len : float
            Window length in seconds to use for FFT.
        time_step : float
            Time step in seconds for windowing.
        num_filters : int
            Number of mel filters to use in the filter bank, defaults to 26.
        use_power : bool
            If true, use the first coefficient of the cepstrum, which is power
            based.  Defaults to false.

        Returns
        -------
        2D array
            MFCCs for each frame.  The first dimension is the time in frames,
            the second dimension is the MFCC values.

        """
        self._sr, proc = preproc(self._filepath,alpha=0.97)

        L = 22
        n = arange(self._num_filters)
        lift = 1+ (L/2)*sin(pi*n/L)
        lift = diag(lift)

        pspec = to_powerspec(proc,self._sr,self._win_len,self._time_step)

        filterbank = self.filter_bank((pspec.shape[1]-1) * 2)


        num_frames = pspec.shape[0]

        self._rep = zeros((num_frames,self._num_coeffs))
        aspec =zeros((num_frames,self._num_filters))
        for k in range(num_frames):
            filteredSpectrum = dot(sqrt(pspec[k,:]), filterbank)**2
            aspec[k,:] = filteredSpectrum
            dctSpectrum = dct_spectrum(filteredSpectrum)
            dctSpectrum = dot(dctSpectrum , lift)
            if not self._use_power:
                dctSpectrum = dctSpectrum[1:]
            self._rep[k,:] = dctSpectrum[:self._num_coeffs]
        self._rep.transpose()
