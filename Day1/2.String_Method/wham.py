import os
import numpy as np
#import jax
import matplotlib.pyplot as plt


#@jax.jit
def jax_mult(A, B):
    return A * B


#@jax.jit
def jax_mult_broadcast(A, B):
    return A * B


def create_bins(q, numbins):
    v_min = np.min(q)
    v_max = np.max(q)
    return np.linspace(v_min, v_max, numbins)


def cnt_pop(qep, qspace, denom, numsims, numbins=50):
    b = np.digitize(qep, qspace) - 1
    # P = np.empty(shape=numbins)
    PpS = np.empty(shape=(numsims, numbins))
    for i in range(numbins):
        md = np.ma.masked_array(denom, mask=~(b == i))
        # P[i] = np.ma.sum(md)
        PpS[:, i] = np.ma.sum(md, axis=1)
    P = np.sum(PpS, axis=0)
    return P, PpS


class WHAM:
    """
    data is 3D: (number of sims, points per sims, number of colvars)
    kval and constr_val are 2D: (number of sims, number of colvars)
    """
    skip = 10
    KbT = 0.001987204259 * 300  # energy unit: kcal/mol
    data = None
    k_val = None
    constr_val = None
    winsize = None
    UB = None
    Fprog = None
    denom = None

    def __init__(self):
        self.path = os.getcwd()
        return

    def setup(self, dist, T, K, centres):
        self.skip = int(dist.shape[1] * 0.1)
        self.KbT = 0.001987204259 * T
        if len(dist.shape) == 2:
            self.data = dist.reshape((dist.shape[0], dist.shape[1], 1))[:, self.skip:, :]
            self.k_val = np.array(K).reshape((dist.shape[0], 1))
            self.constr_val = np.array(centres).reshape((dist.shape[0], 1))
        elif len(dist.shape) == 3:
            self.data = dist
            self.k_val = np.array(K)
            self.constr_val = np.array(centres)
        else:
            raise TypeError("data is not in the right format")
        return

    def calculate_UB3d(self):
        numsims = self.data.shape[0]
        datlength = self.data.shape[1]

        UB = np.empty(shape=(numsims, datlength, numsims), dtype=np.float32)
        for i in range(numsims):
            for j in range(datlength):
                UB[i, j, :] = np.exp(
                   -np.sum(0.5 * self.k_val[:, :] * np.square(self.constr_val[:, :] - self.data[i, j, :]),
                           axis=1) / self.KbT)
        self.UB3d = UB
        return

    def converge(self, threshold=0.01):
        if self.UB is None:
            self.calculate_UB3d()
        numsims = self.data.shape[0]
        datlength = self.data.shape[1]
        if self.Fprog is None:
            Fprog = []
            Fx_old = np.ones(shape=numsims, dtype=np.float32)
        else:
            Fprog = self.Fprog
            Fx_old = Fprog[-1]
        change = 0.2

        while change > threshold:
            expFx_old = datlength * np.exp(Fx_old / self.KbT)
            a = jax_mult(self.UB3d, expFx_old)
            sum = np.sum(a, axis=2)
            denom = np.divide(1, sum, where=sum != 0)
            Fxf = jax_mult_broadcast(self.UB3d, denom[:, :, None])
            Fx = np.sum(Fxf, axis=(0, 1))
            Fx = -self.KbT * np.log(Fx)
            Fx -= Fx[-1]
            Fx_old = Fx
            if len(Fprog) > 1:
                change = np.nanmax(np.abs(Fprog[-1][1:] - Fx[1:]))
            if len(Fprog) > 2:
                prevchange = np.nanmax(np.abs(Fprog[-2][1:] - Fprog[-1][1:]))
                if prevchange < change:
                    print("The iteration started to diverge.")
                    break
            Fprog.append(Fx)
            # print(change)
        self.Fprog = Fprog
        return

    def project_1d(self, cv, numbins_q=50):
        numsims = self.data.shape[0]
        qep = np.sum(self.data * cv, axis=2)
        qspace12 = create_bins(qep, numbins_q)
        if self.denom is None:
            self.calc_denom()
        P, PpS = cnt_pop(qep, qspace12, self.denom, numsims=numsims, numbins=numbins_q)
        rUep = -self.KbT * np.log(P)
        valu = np.min(rUep[:int(numbins_q/2)])
        self.rUep = rUep - valu
        self.rUepPerSim = -self.KbT * np.log(PpS) - valu
        self.qspace12 = qspace12
        return

    def project_2d(self, cv, numbins_q=50):
        numsims = self.data.shape[0]
        datlength = self.data.shape[1]
        q1 = np.sum(self.data * cv[0], axis=2)
        # k_q1 = np.sum(self.constr_val * cv[0], axis=1)
        q2 = np.sum(self.data * cv[1], axis=2)
        # k_q2 = np.sum(self.constr_val * cv[1], axis=1)
        qep = q1 + q2
        qspace12 = create_bins(qep, numbins_q)
        qspace1 = create_bins(q1, numbins_q)
        qspace2 = create_bins(q2, numbins_q)
        Pq12 = np.zeros(shape=numbins_q, dtype=np.float_)
        Pq1 = np.zeros(shape=numbins_q, dtype=np.float_)
        Pq2 = np.zeros(shape=numbins_q, dtype=np.float_)
        Pq2d = np.zeros(shape=(numbins_q, numbins_q), dtype=np.float_)
        PepPersim = np.zeros(shape=(numsims, numbins_q), dtype=np.float_)
        for i in range(numsims):
            for j in range(datlength):
                indq = np.digitize(qep[i, j], qspace12) - 1
                indq1 = np.digitize(q1[i, j], qspace1) - 1
                indq2 = np.digitize(q2[i, j], qspace2) - 1
                Ubias = np.sum(0.5 * self.k_val[:, :] * np.square(self.constr_val[:, :] - self.data[i, j, :]), axis=1)
                denom = np.sum(datlength * np.exp((self.Fprog[-1] - Ubias) / self.KbT))
                Pq12[indq] += 1 / denom
                Pq1[indq1] += 1 / denom
                Pq2[indq2] += 1 / denom
                Pq2d[indq1, indq2] += 1 / denom
                PepPersim[i, indq] += 1 / denom
        rUep = -self.KbT * np.log(Pq12)
        valu = np.min(rUep[:int(numbins_q/2)])
        self.rUep = rUep - valu
        self.rUepPerSim = -self.KbT * np.log(PepPersim) - valu
        self.rUq2d = -self.KbT * np.log(Pq2d) - valu
        self.qspace1 = qspace1
        self.qspace2 = qspace2
        self.qspace12 = qspace12
        return

    def plot_strings(self, title):
        numsims = self.data.shape[0]
        f, a = plt.subplots()
        a.plot(self.qspace12, self.rUep, color="black")
        for i in range(numsims):
            a.plot(self.qspace12, self.rUepPerSim[i], linewidth=0.3)
        plt.title(title)
        # plt.show()
        plt.savefig()
        return

    def calc_denom(self):
        numsims = self.data.shape[0]
        datlength = self.data.shape[1]
        d = np.zeros(shape=(numsims, datlength))
        for i in range(numsims):
            for j in range(datlength):
                Ubias = np.sum(0.5 * self.k_val[:, :] * np.square(self.constr_val[:, :] - self.data[i, j, :]), axis=1)
                denom = np.sum(datlength * np.exp((self.Fprog[-1] - Ubias) / self.KbT))
                d[i, j] = 1 / denom
        self.denom = d
        return