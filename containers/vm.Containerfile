# QEMU x86_64/KVM para a VM de teste (D12): janela GTK com virgl, egl-headless,
# áudio pelo PulseAudio/PipeWire do host.
# Base glibc (Fedora) para aceitar o driver GL do host: com NVIDIA proprietário as
# bibliotecas entram por CDI (--device nvidia.com/gpu=all), e elas não rodam em musl.
FROM registry.fedoraproject.org/fedora:45

RUN dnf install -y --setopt=install_weak_deps=False \
        qemu-system-x86-core qemu-img seabios-bin seavgabios-bin \
        qemu-ui-gtk qemu-ui-opengl qemu-ui-egl-headless \
        qemu-device-display-virtio-gpu qemu-device-display-virtio-gpu-gl \
        qemu-device-display-virtio-gpu-pci qemu-device-display-virtio-gpu-pci-gl \
        qemu-device-display-virtio-vga qemu-device-display-virtio-vga-gl \
        qemu-audio-pa qemu-device-usb-host \
        mesa-dri-drivers mesa-libEGL mesa-libgbm libglvnd-egl libglvnd-opengl \
        dejavu-sans-fonts adwaita-icon-theme \
    && dnf clean all
