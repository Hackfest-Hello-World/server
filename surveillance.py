import cv2
import numpy as np
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
from alert import alert1

# Load YOLOv8 model
model = YOLO("yolov8n.pt")  # You can replace with 'yolov8s.pt' for better accuracy

# DeepSORT initialization
tracker = DeepSort(max_age=30, n_init=3, nms_max_overlap=1.0)

# Video feed
def start1():
    cap = cv2.VideoCapture('3.mp4')

    # Region of Interest (customizable)
    #ROI = [(0, 0), (1000, 1000)]

    def is_inside_roi(box, roi):
        x1, y1, x2, y2 = map(int, box)
        rx1, ry1 = roi[0]
        rx2, ry2 = roi[1]
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        return rx1 <= cx <= rx2 and ry1 <= cy <= ry2

    def get_dynamic_threshold(roi_area, person_area_avg=100000):
        return max(1, roi_area // person_area_avg)

    roi_area = 1000000
    MAX_CAPACITY = get_dynamic_threshold(roi_area)
    HEATMAP_OVERLOAD_THRESHOLD = 120  # average intensity

    # Heatmap initialization
    heatmap = None
    decay_factor = 0.95
    track_ids_in_roi = set()
    tr=0
    c=0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        height, width = frame.shape[:2]
        results = model(frame, verbose=False)
        detections = []
        ROI=[(0,0),(width, height)]
        for box in results[0].boxes:
            cls_id = int(box.cls)
            if cls_id == 0:
                xyxy = box.xyxy[0].cpu().numpy()
                conf = float(box.conf)
                x1, y1, x2, y2 = map(int, xyxy)
                detections.append(([x1, y1, x2 - x1, y2 - y1], conf, 'person'))

        tracks = tracker.update_tracks(detections, frame=frame)
        current_ids = set()

        for track in tracks:
            if not track.is_confirmed():
                continue
            track_id = track.track_id
            ltrb = track.to_ltrb()
            if is_inside_roi(ltrb, [(0,0),(width, height)]):
                current_ids.add(track_id)
                x1, y1, x2, y2 = map(int, ltrb)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f'ID {track_id}', (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Update person count in ROI
        people_count = len(current_ids)

        # Heatmap logic
        if heatmap is None:
            heatmap = np.zeros((frame.shape[0], frame.shape[1]), np.float32)

        for track in tracks:
            if not track.is_confirmed():
                continue
            ltrb = track.to_ltrb()
            if is_inside_roi(ltrb,[(0,0),(width, height)]):
                x1, y1, x2, y2 = map(int, ltrb)
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                #cv2.circle(heatmap, (cx, cy), 30, 1, -1)

        heatmap *= decay_factor

        # ROI-based heatmap averaging
        roi_heatmap = heatmap[ROI[0][1]:ROI[1][1], ROI[0][0]:ROI[1][0]]
        avg_intensity = np.mean(roi_heatmap)

        # Composite overcrowding logic
        overcrowded = people_count > MAX_CAPACITY or avg_intensity > HEATMAP_OVERLOAD_THRESHOLD
        if(overcrowded and not tr):
            alert1(people_count)
            tr=1
        # Display
        cv2.rectangle(frame, ROI[0], ROI[1], (255, 255, 0), 2)
        cv2.putText(frame, f"Count: {people_count}/{MAX_CAPACITY}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)

        if overcrowded:
            cv2.putText(frame, "OVERCROWDING DETECTED!", (20, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)

        # Heatmap blending
        heat_display = cv2.normalize(heatmap, None, 0, 255, cv2.NORM_MINMAX)
        heat_display = np.uint8(heat_display)
        heat_display = cv2.applyColorMap(heat_display, cv2.COLORMAP_JET)

        heat_display_resized = cv2.resize(heat_display, (frame.shape[1], frame.shape[0]))

    # Convert heat_display to 3 channels if frame has 3
        if len(frame.shape) == 3 and frame.shape[2] == 3 and len(heat_display_resized.shape) == 2:
            heat_display_resized = cv2.cvtColor(heat_display_resized, cv2.COLOR_GRAY2BGR)
        blended = cv2.addWeighted(frame, 0.7, heat_display_resized, 0.3, 0)

        cv2.imshow("YOLO + DeepSORT Overcrowding", blended)
        
        
        if cv2.waitKey(1) == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()