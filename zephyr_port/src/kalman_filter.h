#ifndef KALMAN_FILTER_H
#define KALMAN_FILTER_H

typedef struct {
    double x;   // state estimate
    double P;   // estimate error covariance
    double Q;   // process noise covariance
    double R;   // measurement noise covariance
} kalman_1d_t;

void kalman_1d_init(kalman_1d_t *kf, double Q, double R);
double kalman_1d_update(kalman_1d_t *kf, double measurement);

#endif
