

from acousticsim.representations.base import Representation
from acousticsim.representations.helper import preproc,nextpow2

import numpy as np
import scipy as sp
import scipy.signal as sig

from scipy.fftpack import fft,ifft
from scipy.signal import resample, gaussian
from numpy import (pad,log,array,zeros, floor,exp,sqrt,dot,arange,
                    hanning,sin, pi,linspace,log10,round,maximum,minimum,
                    sum,cos,spacing,diag,ceil)

def lpc_ref(signal, order):
    """Compute the Linear Prediction Coefficients.

    Return the order + 1 LPC coefficients for the signal. c = lpc(x, k) will
    find the k+1 coefficients of a k order linear filter:

      xp[n] = -c[1] * x[n-2] - ... - c[k-1] * x[n-k-1]

    Such as the sum of the squared-error e[i] = xp[i] - x[i] is minimized.

    Parameters
    ----------
    signal: array_like
        input signal
    order : int
        LPC order (the output will have order + 1 items)

    Notes
    ----
    This is just for reference, as it is using the direct inversion of the
    toeplitz matrix, which is really slow"""
    if signal.ndim > 1:
        raise ValueError("Array of rank > 1 not supported yet")
    if order > signal.size:
        raise ValueError("Input signal must have a lenght >= lpc order")

    if order > 0:
        p = order + 1
        r = np.zeros(p, signal.dtype)
        # Number of non zero values in autocorrelation one needs for p LPC
        # coefficients
        nx = np.min([p, signal.size])
        x = np.correlate(signal, signal, 'full')
        r[:nx] = x[signal.size-1:signal.size+order]
        phi = np.dot(sp.linalg.inv(sp.linalg.toeplitz(r[:-1])), -r[1:])
        return np.concatenate(([1.], phi))
    else:
        return np.ones(1, dtype = signal.dtype)

def levinson_1d(r, order):
    """Levinson-Durbin recursion, to efficiently solve symmetric linear systems
    with toeplitz structure.

    Parameters
    ---------
    r : array-like
        input array to invert (since the matrix is symmetric Toeplitz, the
        corresponding pxp matrix is defined by p items only). Generally the
        autocorrelation of the signal for linear prediction coefficients
        estimation. The first item must be a non zero real.

    Notes
    ----
    This implementation is in python, hence unsuitable for any serious
    computation. Use it as educational and reference purpose only.

    Levinson is a well-known algorithm to solve the Hermitian toeplitz
    equation:

                       _          _
        -R[1] = R[0]   R[1]   ... R[p-1]    a[1]
         :      :      :          :      *  :
         :      :      :          _      *  :
        -R[p] = R[p-1] R[p-2] ... R[0]      a[p]
                       _
    with respect to a (  is the complex conjugate). Using the special symmetry
    in the matrix, the inversion can be done in O(p^2) instead of O(p^3).
    """
    r = np.atleast_1d(r)
    if r.ndim > 1:
        raise ValueError("Only rank 1 are supported for now.")

    n = r.size
    if n < 1:
        raise ValueError("Cannot operate on empty array !")
    elif order > n - 1:
        raise ValueError("Order should be <= size-1")

    if not np.isreal(r[0]):
        raise ValueError("First item of input must be real.")
    elif not np.isfinite(1/r[0]):
        raise ValueError("First item should be != 0")

    # Estimated coefficients
    a = np.empty(order+1, r.dtype)
    # temporary array
    t = np.empty(order+1, r.dtype)
    # Reflection coefficients
    k = np.empty(order, r.dtype)

    a[0] = 1.
    e = r[0]

    for i in range(1, order+1):
        acc = r[i]
        for j in range(1, i):
            acc += a[j] * r[i-j]
        k[i-1] = -acc / e
        a[i] = k[i-1]

        for j in range(order):
            t[j] = a[j]

        for j in range(1, i):
            a[j] += k[i-1] * np.conj(t[i-j])

        e *= 1 - k[i-1] * np.conj(k[i-1])

    return a, e, k


def _acorr_last_axis(x, nfft, maxlag):
    a = np.real(ifft(np.abs(fft(x, n=nfft) ** 2)))
    return a[..., :maxlag+1] / x.shape[-1]

def acorr_lpc(x, axis=-1):
    """Compute autocorrelation of x along the given axis.

    This compute the biased autocorrelation estimator (divided by the size of
    input signal)

    Notes
    -----
        The reason why we do not use acorr directly is for speed issue."""
    if not np.isrealobj(x):
        raise ValueError("Complex input not supported yet")

    maxlag = x.shape[axis]
    nfft = 2 ** nextpow2(2 * maxlag - 1)

    if axis != -1:
        x = np.swapaxes(x, -1, axis)
    a = _acorr_last_axis(x, nfft, maxlag)
    if axis != -1:
        a = np.swapaxes(a, -1, axis)
    return a

def lpc(signal, order, axis=-1):
    """Compute the Linear Prediction Coefficients.

    Return the order + 1 LPC coefficients for the signal. c = lpc(x, k) will
    find the k+1 coefficients of a k order linear filter:

      xp[n] = -c[1] * x[n-2] - ... - c[k-1] * x[n-k-1]

    Such as the sum of the squared-error e[i] = xp[i] - x[i] is minimized.

    Parameters
    ----------
    signal: array_like
        input signal
    order : int
        LPC order (the output will have order + 1 items)

    Returns
    -------
    a : array-like
        the solution of the inversion.
    e : array-like
        the prediction error.
    k : array-like
        reflection coefficients.

    Notes
    -----
    This uses Levinson-Durbin recursion for the autocorrelation matrix
    inversion, and fft for the autocorrelation computation.

    For small order, particularly if order << signal size, direct computation
    of the autocorrelation is faster: use levinson and correlate in this case."""
    n = signal.shape[axis]
    if order > n:
        raise ValueError("Input signal must have length >= order")

    r = acorr_lpc(signal, axis)
    return levinson_1d(r, order)

class Formants(Representation):

    def __init__(self, filepath,max_freq, num_formants, win_len,
                    time_step, attributes = None, window_shape = 'gaussian'):
        Representation.__init__(self, filepath, (0,max_freq), attributes)
        self._num_formants = num_formants

        self._win_len = win_len
        self._window_shape = window_shape
        if self._window_shape == 'gaussian':
            self._win_len *= 2

        self._time_step = time_step

    def __getitem__(self,key):
        item = Representation.__getitem__(self, key)
        return np.array([x[0] for x in item], dtype = np.float32)

    def to_array(self, value='formant'):
        times = sorted(self._rep.keys())
        ex = next(iter(self._rep.values()))
        try:
            frame_len = len(ex)
        except:
            frame_len = 1

        output = np.zeros((len(times),frame_len))
        for i, t in enumerate(times):
            if value == 'formant':
                output[i,:] = [x[0] for x in self._rep[t]]
            elif value == 'bandwidth':
                output[i,:] = [x[1] for x in self._rep[t]]
        return output

class LpcFormants(Formants):

    def __init__(self, filepath,max_freq, num_formants, win_len,
                    time_step, attributes = None, window_shape = 'gaussian'):
        Formants.__init__(self, filepath,max_freq, num_formants, win_len,
                    time_step, attributes = None, window_shape = 'gaussian')
        self.process()

    def process(self):
        self._rep = dict()
        new_sr = 2 *self._freq_lims[1]
        alpha = np.exp(-2 * np.pi * 50 * (1/new_sr))
        self._sr, proc = preproc(self._filepath,alpha=alpha)
        proc = resample(proc,int(ceil(proc.shape[0]/(self._sr/new_sr))))
        nperseg = int(self._win_len*new_sr)
        nperstep = int(self._time_step*new_sr)

        if self._window_shape == 'gaussian':
            window = gaussian(nperseg+2,0.45*(nperseg-1)/2)[1:nperseg+1]
        else:
            window = hanning(nperseg+2)[1:nperseg+1]
        indices = arange(int(nperseg/2), proc.shape[0] - int(nperseg/2) + 1, nperstep)
        num_frames = len(indices)

        formants = zeros((num_frames,self._num_formants))
        for i in range(num_frames):
            X = proc[indices[i]-int(nperseg/2):indices[i]+int(nperseg/2)]
            X = X * window
            A, e, k  = lpc(X,self._num_formants*2)

            rts = np.roots(A)
            rts = np.array([r for r in rts if np.imag(r) >= 0])
            angz = np.arctan2(np.imag(rts), np.real(rts))
            frqs = angz * (new_sr / (2 * np.pi))
            frq_inds = np.argsort(frqs)
            frqs = frqs[frq_inds]
            #print(frqs)
            bw = -1/2*(new_sr/(2*np.pi))*np.log(np.abs(rts[frq_inds]))
            formants = list()
            for j,f in enumerate(frqs):
                if f < 50:
                    continue
                if f > self._freq_lims[1] - 50:
                    continue
                formants.append((f,bw[j]))
            missing = self._num_formants - len(formants)
            if missing:
                formants += [(None,None)] * missing
            self._rep[indices[i]/new_sr] = formants
            #raise(ValueError)


