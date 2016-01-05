import unittest
import numpy as np
from astroalign import align


def gauss(shape=(11, 11), center=None, sx=2, sy=2):
    "Returns a Gaussian of given shape, normalized to 1."
    h, w = shape
    if center is None:
        center = ((h - 1) / 2., (w - 1) / 2.)
    x0, y0 = center
    x, y = np.meshgrid(range(w), range(h))
    krnl = np.exp(-0.5 * ((x - x0) ** 2 / sx ** 2 + (y - y0) ** 2 / sy ** 2))
    krnl /= krnl.sum()
    return krnl


class TestAlign(unittest.TestCase):
    def setUp(self):
        from scipy import signal
        self.h = 512  # image height
        self.w = 512  # image width
        kh = 10  # kernel height
        kw = 10  # kernel width
        noise_level = 500  # counts
        num_stars = 1500
        psf = gauss(shape=(21, 21), sx=1.5, sy=1.5)

        # Transformation parameters
        self.x_offset = 10
        self.y_offset = -20
        self.rot_angle = 50. * np.pi / 180.

        big_r = (0.5 * np.sqrt(self.h ** 2 + self.w ** 2)
                 + max(abs(self.x_offset), abs(self.y_offset)))

        self.image_ref = np.random.poisson(noise_level,
                                           size=(self.h + kh, self.w + kw)
                                           ).astype('float64')
        self.image = np.random.poisson(noise_level,
                                       size=(self.h + kh, self.w + kw)
                                       ).astype('float64')

        # x and y of stars in the ref frame (int's)
        self.star_refx = np.random.randint(low=int(-big_r) + self.w / 2,
                                           high=int(big_r) + self.w / 2,
                                           size=(num_stars,))
        self.star_refy = np.random.randint(low=int(-big_r) + self.h / 2,
                                           high=int(big_r) + self.h / 2,
                                           size=(num_stars,))
        # Fluxes of stars
        a, m = 0.8, 3. * self.image_ref.std()
        self.star_f = (1. + np.random.pareto(a, num_stars)) * m
        # self.star_f = 1.*np.random.exponential(1600., size=(num_stars,))

        # inframe will contain the stars in the reference image
        inframe = []
        ymax, xmax = self.image_ref.shape
        for x, y, f in zip(self.star_refx, self.star_refy, self.star_f):
            if x > 0 and x < xmax and y > 0 and y < ymax:
                inframe.append((int(x), int(y), f))
        self.ref_cols, self.ref_rows, self.ref_flux = \
            np.array(inframe).astype(int).T

        self.image_ref[self.ref_rows, self.ref_cols] += self.ref_flux
        self.image_ref = signal.convolve2d(self.image_ref, psf, mode='same')
        self.image_ref = self.image_ref[kh // 2: -kh // 2, kw // 2: -kw // 2]
        # Adjust here the positions of rows and cols after cropping image
        self.ref_cols -= kw // 2
        self.ref_rows -= kh // 2

        newx, newy = [], []
        for x, y in zip(self.star_refx, self.star_refy):
            x -= self.w / 2
            y -= self.h / 2
            xp = (x * np.cos(self.rot_angle) - y * np.sin(self.rot_angle)
                  + self.x_offset)
            yp = (x * np.sin(self.rot_angle) + y * np.cos(self.rot_angle)
                  + self.y_offset)
            xp += self.w / 2
            yp += self.h / 2
            newx.append(xp)
            newy.append(yp)
        # x and y of stars in the new frame (float's)
        self.star_newx = np.array(newx)
        self.star_newy = np.array(newy)

        inframe = []
        ymax, xmax = self.image.shape
        for x, y, f in zip(self.star_newx, self.star_newy, self.star_f):
            if (x > 0 and x < xmax and y > 0 and y < xmax):
                inframe.append((int(x), int(y), f))
        self.new_cols, self.new_rows, self.new_flux = \
            np.array(inframe).astype(int).T

        self.image[self.new_rows, self.new_cols] += self.new_flux
        self.image = signal.convolve2d(self.image, psf, mode='same')
        self.image = self.image[kh // 2: -kh // 2, kw // 2: -kw // 2]
        # Adjust here the positions of rows and cols after cropping image
        self.new_cols -= kw // 2
        self.new_rows -= kh // 2

        self.star_ref_pos = np.array(zip(self.ref_cols, self.ref_rows))
        self.star_new_pos = np.array(zip(self.new_cols, self.new_rows))

    def test_find_affine_transform(self):

        star_ref_pos_b = self.star_ref_pos[np.argsort(self.ref_flux)]
        star_new_pos_b = self.star_new_pos[np.argsort(self.new_flux)]

        m = align.find_affine_transform(star_new_pos_b[50::-1],
                                        star_ref_pos_b[70::-1])
        alpha = self.rot_angle
        xoff_corrected = ((1 - np.cos(alpha)) * self.w / 2 + np.sin(alpha) *
                          self.h / 2 + self.x_offset)
        yoff_corrected = (-np.sin(alpha) * self.w / 2 + (1 - np.cos(alpha)) *
                          self.h / 2 + self.y_offset)
        mtrue = np.array([[np.cos(alpha), -np.sin(alpha), xoff_corrected],
                          [np.sin(alpha), np.cos(alpha), yoff_corrected]])
        # Pass the test if less than 2% relative error in result
        rel_error = np.linalg.norm(m - mtrue, 1) / np.linalg.norm(mtrue, 1)
        self.assertLess(rel_error, 2E-2)

    def test_align_image(self):
        image_aligned = align.align_image(self.image, self.image_ref)
        # pixel comparison is not good, doesn't work. Compare catalogs.
        full_algn = image_aligned.copy()
        full_algn[image_aligned == 0] = np.median(image_aligned)
        import sep
        bkg = sep.Background(full_algn)
        thresh = 3.0 * bkg.globalrms
        allobjs = sep.extract(full_algn - bkg.back(), thresh)
        allxy = np.array([[obj['x'], obj['y']] for obj in allobjs])

        from scipy.spatial import KDTree
        ref_coordtree = KDTree(self.star_new_pos)

        # Compare here srcs list with self.star_ref_pos
        num_sources = 0
        for asrc in allxy:
            found_source = ref_coordtree.query_ball_point(asrc, 3)
            if found_source:
                num_sources += 1
        fraction_found = float(num_sources) / float(len(allxy))
        self.assertGreater(fraction_found, 0.85)

    def test_find_sources(self):
        srcs = align.find_sources(self.image_ref)

        from scipy.spatial import KDTree
        ref_coordtree = KDTree(self.star_ref_pos)

        # Compare here srcs list with self.star_ref_pos
        num_sources = 0
        for asrc in srcs:
            found_source = ref_coordtree.query_ball_point(asrc, 3)
            if found_source:
                num_sources += 1
        fraction_found = float(num_sources) / float(len(srcs))
        self.assertGreater(fraction_found, 0.85)

    def tearDown(self):
        self.image = None
        self.image_ref = None


if __name__ == "__main__":
    unittest.main()