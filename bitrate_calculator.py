class BitrateCalculator:
    def calculate_bitrate(self, size_mb, duration_sec, audio_bitrate_kbps_str, remove_audio_bool):
        if duration_sec <= 0:
            raise ValueError("Duration must be positive to calculate bitrate.")
        
        total_kbits = size_mb * 8192 # Convert MB to kilobits (1 MB = 8192 Kbits)

        audio_bitrate_kbps = 0
        if not remove_audio_bool:
            try:
                audio_bitrate_kbps = int(audio_bitrate_kbps_str.replace('k', ''))
            except ValueError:
                audio_bitrate_kbps = 128 # Fallback if parsing fails

        # Account for potential overhead (container, metadata)
        overhead_factor = 0.08
        target_kbits_for_streams = total_kbits * (1 - overhead_factor)

        min_audio_kbits_needed = audio_bitrate_kbps * duration_sec
        
        if target_kbits_for_streams <= min_audio_kbits_needed:
            # If target size is too small for desired audio, reduce audio and assign remaining to video
            if target_kbits_for_streams > 0 and duration_sec > 0:
                # Prioritize a minimum video bitrate, even if it means compressing audio more aggressively
                min_video_bitrate_kbps = 50 # A reasonable minimum for video
                
                # Calculate max audio kbits possible given min video and total target
                max_audio_kbits_possible = target_kbits_for_streams - (min_video_bitrate_kbps * duration_sec)
                
                if max_audio_kbits_possible < 0:
                    # If even min_video_bitrate makes total negative, means target_kbits_for_streams is too low
                    # In this edge case, we'll just distribute what's available
                    audio_bitrate_kbps = max(0, int(target_kbits_for_streams * 0.3 / duration_sec))
                    video_bitrate_kbps = max(0, int(target_kbits_for_streams * 0.7 / duration_sec))
                else:
                    audio_bitrate_kbps = int(max_audio_kbits_possible / duration_sec)
                    if audio_bitrate_kbps < 32 and not remove_audio_bool: # Ensure minimum audio bitrate if audio is kept
                        audio_bitrate_kbps = 32
                    
                    video_kbits_per_sec = (target_kbits_for_streams - (audio_bitrate_kbps * duration_sec)) / duration_sec
                    video_bitrate_kbps = max(min_video_bitrate_kbps, int(video_kbits_per_sec))
            else:
                video_bitrate_kbps = 50
                audio_bitrate_kbps = 32 if not remove_audio_bool else 0
        else:
            video_kbits_per_sec = (target_kbits_for_streams - (audio_bitrate_kbps * duration_sec)) / duration_sec
            video_bitrate_kbps = max(50, int(video_kbits_per_sec)) # Ensure minimum video bitrate
        
        print(f"Calculated Video Bitrate: {video_bitrate_kbps} kbps, Audio Bitrate: {audio_bitrate_kbps} kbps")
        return video_bitrate_kbps, audio_bitrate_kbps