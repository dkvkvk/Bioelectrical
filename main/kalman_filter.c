#include "kalman_filter.h"

void kalman_1d_init(kalman_1d_t *kf, double Q, double R)
{
    kf->x = 0.0;
    kf->P = 1.0;
    kf->Q = Q;
    kf->R = R;
}

double kalman_1d_update(kalman_1d_t *kf, double measurement)
{
    // first call: seed with measurement
    if (kf->P >= 1.0) {
        kf->x = measurement;
        kf->P = kf->R;
    }

    // predict
    kf->P += kf->Q;

    // update
    double K = kf->P / (kf->P + kf->R);
    kf->x += K * (measurement - kf->x);
    kf->P *= (1.0 - K);

    return kf->x;
}
